import os
import sys
pythonpath = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0,pythonpath)

from pathlib import Path
from utils.log import logger
from utils.sql import sql_dataset
from twitter_agent.twitter_bot import TwitterBot
from twitter_agent.twitter_planner import TwitterPlanner
from datetime import datetime,timedelta
import json
import random
import time
import pdb
import asyncio
from concurrent.futures import ThreadPoolExecutor
from utils.utils import convert_time_us
from utils.generation import *
import pdb
from paper_agent.paper_agent import PaperAgent
from twitter_agent.twitter_bot import TwitterBot
from xhs_agent.xhs_bot import XiaohongshuBot
from utils.log import logger
import requests
import zipfile
import os, re
from typing import List, Dict, Optional
from utils.prompt import *
from bs4 import BeautifulSoup

ROOT_PATH = "D:\\论文agent\\papers\\"
'''
从服务器上下载zip到 本地，提取论文的：title, abstract, file_path

根据论文的title爬取论文的基本信息，保存到数据库中'''

class ScrapPapers():
    def __init__(self,log_path='./logs/paperagent/scrap_paper/scrap_paper_log.log'):
        self.log_path = log_path
        self.log = logger(filename=self.log_path)
        self.database = sql_dataset('papers')  # 论文数据库
    


    def parse_markdown_papers(self,extract_path: str, language: Optional[str] = None) -> List[Dict[str, str]]:
        """
        仅解析并返回每篇论文的关键信息：
        [
        {
            "title": "...",
            "authors": "...",
            "arxiv_url": "https://arxiv.org/abs/....",
            "abstract": "...",
            "pic_path": "/abs/path/to/figs/1.png"
        },
        ...
        ]
        """
        # 1) 选择要解析的 md 文件
        all_files = os.listdir(extract_path)
        if language == "English":
            cand = [f for f in all_files if f.endswith("_en.md")]
        elif language == "Chinese":
            cand = [f for f in all_files if f.endswith("_ch.md")]
        else:
            cand = [f for f in all_files if f.endswith(".md")]
        if not cand:
            return []
        md_file = os.path.join(extract_path, cand[0])

        with open(md_file, "r", encoding="utf-8") as f:
            text = f.read()

        # 2) 以每个二级标题 "## <title>" 为一个论文分段
        #    用正则把每篇的位置切出来（包含标题行）
        sec_iter = list(re.finditer(r"(?m)^##\s+(?P<title>.+?)\s*$", text))
        papers: List[Dict[str, str]] = []
        if not sec_iter:
            return papers

        for i, m in enumerate(sec_iter):
            start = m.start()
            end = sec_iter[i + 1].start() if i + 1 < len(sec_iter) else len(text)
            section = text[start:end]

            # ---- 解析每个 section 的 5 个字段 ----
            # 2.1 标题
            title = m.group("title").strip()

            # 2.2 作者（形如："> Authors: xxx"）
            m_auth = re.search(r"(?mi)^>\s*Authors:\s*(.+?)\s*$", section)
            authors = m_auth.group(1).strip() if m_auth else ""

            # 2.3 arXiv 链接（形如：https://arxiv.org/abs/xxxx）
            m_url = re.search(r"(?mi)^https?://arxiv\.org/\S+\b", section)
            arxiv_url = m_url.group(0).strip() if m_url else ""

            # 2.4 摘要：从 "### Abstract" 下一行开始，直到下一个特征（图片/评述/下一个段落标题）
            abstract = ""
            m_abs = re.search(r"(?mi)^###\s*Abstract\s*$", section)
            if m_abs:
                abs_start = m_abs.end()
                # 截到下一个强分隔符：图片、Review、下一个 ### 或 ## 标题 或段尾
                m_abs_end = re.search(
                    r"(?ms)(?=^\s*!\[)|(?=^\s*\*\*Review\*\*)|(?=^###\s)|(?=^##\s)", 
                    section[abs_start:]
                )
                if m_abs_end:
                    abstract = section[abs_start:abs_start + m_abs_end.start()]
                else:
                    abstract = section[abs_start:]
                abstract = abstract.strip()

            # 2.5 图片路径：取该 section 内第一张图片
            #    例：![](figs/1.png) → 拼接为绝对路径
            pic_path = ""
            m_img = re.search(r"!\[.*?\]\((?P<path>[^)]+)\)", section)
            if m_img:
                raw_path = m_img.group("path").strip()
                if os.path.isabs(raw_path):
                    pic_path = raw_path
                else:
                    # 将相对路径按 md 中的路径层级拼入 extract_path
                    # e.g. "figs/1.png" → /abs/extract_path/figs/1.png
                    parts = [p for p in raw_path.split("/") if p]
                    pic_path = os.path.join(extract_path, *parts)

            papers.append({
                "title": title,
                "authors": authors,
                "arxiv_url": arxiv_url,
                "abstract": abstract,
                "pic_path": [pic_path],
            })

        return papers




    def analyze_md_document(self,zip_file_path, root_path=ROOT_PATH):
        '''将下载到本地的论文信息，解析md文档，提取论文的title, abstract, file_path'''
        save_path = os.path.join(root_path,"extracted")
        zip_name = os.path.splitext(os.path.basename(zip_file_path))[0]
        extract_path = os.path.join(save_path, zip_name)  # 设置解压路径
        # 如果保存路径不存在，则创建路径
        os.makedirs(extract_path, exist_ok=True)
        with zipfile.ZipFile(zip_file_path, 'r') as zip_ref:
            zip_ref.extractall(save_path)  # 解压到指定文件夹
        
        # 获取图片文件夹路径
        pic_folder = [f.name for f in Path(extract_path).iterdir() if f.is_dir()][0]
        pic_folder = os.path.join(extract_path, pic_folder)

        # 提取并解析英文内容
        papers = self.parse_markdown_papers(extract_path, language='English')

        return papers



    async def scrap_arxiv(self,title: str,domain:str=None) -> dict:
        """
        输入：文章标题
        功能：根据标题搜索arxiv，获取文章摘要，并生成论文的关键词列表
        输出：{"title": ..., 'abstract': ...}
        """
        # 1. 构造搜索URL
        search_url = f"https://arxiv.org/search/?query={requests.utils.quote(title)}&searchtype=all&source=header"
        headers = {
            "User-Agent": "Mozilla/5.0"
        }
        # 2. 请求搜索页面
        resp = requests.get(search_url, headers=headers, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # 3. 找到第一个搜索结果
        result = soup.find("li", class_="arxiv-result")
        if not result:
            return {"Title": title, "Abstract": None, "Gene_keywords": None,"Authors":None,"URL":None}

        # 4. 获取arxiv详情页链接
        link_tag = result.find("p", class_="title is-5 mathjax")
        if not link_tag:
            return {"Title": title, "Abstract": None, "Gene_keywords": None,"Authors":None,"URL":None}
        # 标题文本
        found_title = link_tag.text.strip().replace("\n", " ")
        # 摘要
        abstract_tag = result.find("span", class_="abstract-full has-text-grey-dark mathjax")
        abstract = abstract_tag.text.strip().replace("Abstract: ", "") if abstract_tag else None
        #论文url
        link_tag = result.find("p", class_="list-title is-inline-block").find("a")
        paper_url = link_tag['href'] if link_tag and link_tag.has_attr('href') else None
        # 论文作者
        authors = []
        authors_p = result.find("p", class_="authors")
     
        if authors_p:
            authors = [a.get_text(strip=True) for a in authors_p.find_all("a")]

        # LLM生成论文关键字
        try_num  =  0
        while try_num < 5:
            response = await general_generation([{"role":"system","content":generate_paper_keywords_prompt()},{"role":"user","content":abstract}]) # 32B
            if not response:
                try_num += 1
                continue
            else:
                keywords = response.split(',')
                keywords = [s.strip() for s in keywords if s.strip()]
                self.log.info(f'生成的论文关键字是：{keywords}')
                break
        return {"Title": found_title,"Abstract": abstract,"URL": paper_url,"Gene_keywords": keywords,"Authors":authors}
    

    async def parse_paper_domain(self,domain,zip_file_path):
        '''把从md解析出来的 文件信息，判断是否属于domain领域，然后插入数据库中'''
        papers_info = self.analyze_md_document(zip_file_path)
        pdb.set_trace()
        for paper in papers_info:
            if len(paper['pic_path']) ==  0 or paper['pic_path'] == None:
                self.log.info(f'论文{paper["title"]}没有图片，跳过')
                continue 
            self.log.info(f'论文标题是：{paper["title"]}')
            paper_info = await self.scrap_arxiv(title=paper["title"])

            # 根据论文摘要判断该论文是否是domain领域
            _,response = await general_generation_think([{"role":"system","content":filter_paper_domain_prompt(domain=domain)},
                                                         {"role":"user","content":paper_info["Abstract"]}])
            if response is None:
                self.log.error(f'生成结果失败，跳过')
                continue
            
            select_sql = f'''SELECT * FROM papers_info WHERE URL='{paper_info["URL"]}';'''
            select_result = self.database.get_dict_data_sql(select_sql)
            if not select_result:
                if '是' in response:
                    self.log.info(f'论文 {paper_info["Title"]}，属于{domain}领域')
                    domain_list =  json.dumps([domain])
                else:   
                    self.log.info(f'论文 {paper_info["Title"]}，不属于{domain}领域')
                    # domain_list =  json.dumps([])
                    continue
                insert_sql = '''INSERT INTO `papers_info` (`Title`, `Authors`, `URL`, `Abstract`, `Field`, `Gene_keywords`,`Image_path`) VALUES (%s,%s,%s,%s,%s,%s,%s)'''
                self.database.operation(insert_sql,(paper_info["Title"],json.dumps(paper_info["Authors"]),paper_info["URL"],paper_info["Abstract"],domain_list,json.dumps(paper_info["Gene_keywords"]),paper["pic_path"][0]))
                
                self.log.info(f'已将论文 {paper_info["Title"]} 的信息插入数据库')
            else:
                field = json.loads(select_result[0]['Field'])
                if '是' in response:
                    self.log.info(f'论文 {paper_info["Title"]}，属于{domain}领域')
                    # 更新该论文的domain ，后续更新领域的时候插入图片
                    if domain not in field:
                        field.append(domain)
                update_sql = '''UPDATE papers_info SET Field=%s WHERE title=%s AND URL=%s AND Image_path=%s;;'''
                self.database.operation(update_sql,(json.dumps(field),paper_info["Title"],paper_info["URL"],paper["pic_path"][0]))
                self.log.info(f'已更新数据库中{paper_info["Title"]}的Field')

        self.log.info(f'{zip_file_path} 中的论文已经全部处理完成')



# log = logger(filename='./logs/papers_download/papers_download_log.log')
# def main():
#     # 从服务器上下载文件
#     while True:
#         pdb.set_trace()

#         # 服务器下载文件的URL（替换为你的FastAPI服务器URL）
#         url = "http://www.chattydog.top/gzh/download/"

#         # 本地保存文件的目录
#         local_save_dir = "D:\\论文agent\\papers\\zip_folder"

#         # 如果目录不存在则创建
#         if not os.path.exists(local_save_dir):
#             os.makedirs(local_save_dir)

#         # 发起下载请求
#         response = requests.get(url)

#         # 检查请求是否成功
#         if response.status_code == 200: 
#             # 从响应的headers中提取文件名
#             content_disposition = response.headers.get("content-disposition")
            
#             if content_disposition:
#                 filename = content_disposition.split("filename=")[-1].strip('"')
#             else:
#                 # 如果header中没有文件名, 可以设置一个默认文件名
#                 filename = "downloaded_file.zip"
#             # 定义本地保存的文件路径
#             local_file_path = os.path.join(local_save_dir, filename)
#             if not os.path.exists(local_file_path):
#                 # 将下载的文件内容保存到本地
#                 with open(local_file_path, "wb") as f:
#                     f.write(response.content)
#                 log.info(f"文件 {filename} 已成功下载到 {local_save_dir}")
#                 # run(zip_file_path=local_file_path)
#                 a  = ScrapPapers()
#                 a.analyze_md_document(zip_file_path=local_file_path)
#                 time.sleep(3600)
#             else:
#                 log.info(f"文件 {filename} 已存在，没有最新文件需要下载")
#                 time.sleep(3600)
#         else:
#             log.info(f"下载文件失败，状态码：{response.status_code}")
#             time.sleep(3600)


if __name__ == "__main__":
    a  = ScrapPapers()
    asyncio.run(a.parse_paper_domain(zip_file_path='D:\\论文agent\\papers\\zip_folder\\2025-10-01.zip', domain='Large Language Models for Recommendation'))
