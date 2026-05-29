import requests
import chardet
from trafilatura import bare_extraction
from typing import List, TypedDict, Dict
import os
import asyncio
import aiohttp
import time
import pyperclip
from itertools import islice
import re
from pathlib import Path
import pytz
# from docx import Document
# from docx.shared import Inches
from io import BytesIO
from datetime import datetime
import cv2
import numpy as np
from PIL import Image
import os
import io
import base64

# from docx.image.exceptions import UnrecognizedImageError
# A timer
def timer(func):
    def func_wrapper(*args, **kwargs):
        from time import time
        time_start = time()
        result = func(*args, **kwargs)
        time_end = time()
        time_spend = time_end - time_start
        print('%s cost time: %.3f s' % (func.__name__, time_spend))
        return result
    return func_wrapper

# Fetch the content of a url
MIN_ARTICLE_LENGTH = 10
@timer
async def fetch_url_content(url:str, use_proxy=False) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36 Edg/118.0.2088.69"
    }
    proxies = None if use_proxy else None
    try:
        r = requests.get(url, headers=headers, verify=False, proxies=proxies, timeout=7)
        r.raise_for_status()
        encoding = chardet.detect(r.content)['encoding']
        if not encoding:
            encoding = 'utf-8'
        text = r.content.decode(encoding=encoding)
        content = bare_extraction(text, favor_precision=True, include_comments=False)
    except Exception as e:
        print(e)
        content = None
    if not content or len(content) < MIN_ARTICLE_LENGTH:
        return ""
    return content

# load offical organization names from platform (e.g. weibo)
def load_offical_organization_names(name_list_path:str) -> set:
    with open(name_list_path, 'r',encoding="utf-8") as file:
        name_list = file.readlines()
    name_list = [name.strip() for name in name_list]
    return set(name_list)



# 根据图像链接下载图片
def download_image(img_url: str, save_path: str) ->None:
    '''
    根据图像链接下载图片，并保存在相应的文件夹下
    
    参数：
         img_url: 下载链接
         save_path: 图片保存路径
    
    返回：无

    '''
    try:
        # 设置不使用代理
        session = requests.Session()
        session.trust_env = False
        # 发送请求
        response = session.get(img_url, stream=True, verify=False)
        response.raise_for_status()  # 检查请求是否成功

        # response = requests.get(img_url, stream=True)

        if response.status_code == 200:
            with open(save_path, 'wb') as file:
                for chunk in response.iter_content(1024):
                    file.write(chunk)
            print('成功保存图片！')       
        else:
            print(f"从链接{img_url}下载图片失败！！")
    except requests.exceptions.RequestException as e:
        print(f"下载图片时发生请求异常：{e}")
    except Exception as e:
        print(f"下载图片时发生异常：{e}！！")


# 定义爬取内容的数据结构（前边的filter_result是这个结构）
class TopicTerm(TypedDict):
    nick_name: str
    content: str 
    img_src: List[str]
    topic: str


# 检查路径是否合法
def sanitize_path(path):
    # 替换掉非法字符
    illegal_chars = [":", "*", "?", "<", ">", "|", "\"", "/", "\\"]
    for char in illegal_chars:
        path = path.replace(char, "_")
    return path


# 将微博内容写入文件
async def write_topic_content_to_files(all_topic_result: List[List[TopicTerm]], root_path: str,download=True) -> None:
# async def write_topic_content_to_files(all_topic_result: List[List[Dict[str, str, List[str],str]]], root_path: str) -> None:
    '''
    基于热搜词条topic，将all_topic_result中的content写入topic_content.txt文件中, 并将相应topic图片存储在topic/image/文件夹下。
    
    参数： 
        all_topic_result：[[{},{}],[],[]]子列表是同一个topic的内容
        root_path：文件保存的根目录
        download:是否下载图片，默认是True

    返回：无

    '''
    # 判断根目录文件夹是否存在
    if not os.path.exists(root_path):
        os.makedirs(root_path)
    
    # tasks = []
    for topic_list in all_topic_result:
        # 取第一个item判断topic文件夹和topic/image文件夹是否存在，如果不在则新建
        if topic_list:
            topic = topic_list[0]['topic']

            # 检查是否有图片
            has_images = any(item['images'] for item in topic_list)

            if not has_images:
                # 如果没有图片，跳过创建文件夹
                continue
            
            topic = sanitize_path(topic)
            
            # 有图片，则判断每个topic文件夹是否存在，如果不在则新建
            topic_path = os.path.join(root_path, topic)
            os.makedirs(topic_path,exist_ok=True)
            
            # 判断每个topic/images文件夹是否存在，如果不在则新建
            topic_image_path = os.path.join(topic_path, 'images')
            os.makedirs(topic_image_path,exist_ok=True)

        # 如果没有图片，则舍弃掉这个话题
        # all_image_empty = all(not item['img_src'] for item in topic_list)
        # if not all_image_empty:  # 如果某个topic存在图片，则记录这个topic的content，并下载图片
        for item in topic_list:
            # topic = item['topic']
            content = item['content']
            # nick_name = item['nick_name']
            img_src_list = item.get('images',[])   

            # 对content进行清洗，去掉话题#/@/..的微博视频等
            content = re.sub(r'【[^【】]*】', '', content)
            content = re.sub(r'#\S+#', '', content)
            content = re.sub(r'@\S+\s*', '', content) 
            content = re.sub(r'L\S+的微博视频', '', content)
            content = re.sub(r'O网页链接', '', content)
            content = re.sub(r'O\S+ \|', '', content)
            # print(content)

            # 将清洗后的content写入topic_content.txt文件
            topic_content_file = os.path.join(topic_path, f"{topic}_content.txt")
            with open(topic_content_file, 'a', encoding='utf-8') as file:
                file.write(content + '\n\n\n\n\n')
                # file.write(content + '\t' + nick_name + '\n\n')  # 带上发布该条新闻的账号昵称    

            # 如果不存在图片的话，就舍弃这个topic
            # 下载并保存图片到topic/image文件夹中
            for idx, img_src in enumerate(img_src_list):
                img_name = f"image_{idx}.jpg"
                img_save_path = os.path.join(topic_image_path, img_name)
                download_image(img_src, img_save_path)


# 打开content.txt文件
def open_topic_content_file(topic_content_file_path:str) -> str:
    with open(topic_content_file_path,'r',encoding='utf-8') as file:
            content = file.read()
    return content 

# 获取所有文件和文件夹
import pdb
def find_txt_and_images(root_path):
    txt_contents = []
    image_paths = []
    # 递归遍历 root_path 目录下的所有文件和文件夹
    for path in Path(root_path).rglob('*'):
        # 查找 .txt 文件
        if path.is_file():
            if path.suffix == '' or path.suffix == '.txt':  # txt
                txt_file_path = path
                # 读取txt
                txt_contents = open_topic_content_file(txt_file_path).split("\n\n\n\n\n")

        # 如果当前目录是 image 文件夹，查找图片
        if path.is_dir() and 'image' in path.name.lower():
            for image_file in path.glob('*'):
                if image_file.suffix.lower() in ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff', '.svg']:
                    image_paths.append(image_file)
    txt_contents = [item for item in txt_contents if item]
    image_paths = [str(item) for item in image_paths]
    return txt_contents, image_paths

def convert_time_us(post_time_str):
    # time_obj_utc = datetime.fromisoformat(post_time_str.replace("Z", "+00:00"))
    # 设置时区为美国东部时间（纽约时间）
    china_tz = pytz.timezone('America/New_York')
    time_obj_china = post_time_str.astimezone(china_tz)
    post_time = time_obj_china.replace(tzinfo=None)
    return post_time



# 将文本和图像写入word文档
# def add_text_and_images_to_word(text, image_sources, save_path):
#     doc = Document()
#     doc.add_paragraph(text)
#     # print(f'传入的图像source是：{image_sources}')
#     # 处理图片
#     for img_source in image_sources:
#             # 如果是本地文件路径，直接插入图片
#             if os.path.exists(img_source):
#                 print(f"插入图片: {img_source}")
#                 img_source = Path(img_source).resolve()  # 转换成绝对路径
#                 try:
#                     doc.add_picture(str(img_source), width=Inches(4))  # 调整图片的宽度
#                 except UnrecognizedImageError:
#                     print(f"无法识别图片: {img_source}，跳过此图片")
#                     continue  # 跳过当前图片，继续处理下一张
#             else:
#                 print(f"图片路径不存在: {img_source}")
#     # 保存Word文档
#     doc.save(save_path)
#     print(f"文档已保存为: {save_path}")
  
    
    
# 去掉图片水印
def process_image(image_path):
    try:
        os.getcwd()
        dir_name, file_name = os.path.split(image_path)  # 获取目录和文件名
        base_name, ext = os.path.splitext(file_name)  # 获取文件名和扩展名
        new_file_name = base_name + "_processed" + ext
        newPath =  os.path.join(dir_name, new_file_name)
        img = cv2.imread(image_path,1)
        # img = cv2.imread(str(image_path),1)
        if img is None:
            print(f"无法加载图片，路径: {image_path}")
            return ''
        hight,width,depth=img.shape[0:3]

        #截取
        cropped = img[int(hight*0.8):hight, int(width*0.7):width]  # 裁剪坐标为[y0:y1, x0:x1]
        cv2.imwrite(newPath, cropped)

        imgSY = cv2.imread(newPath,1)
        # imgSY = cv2.imdecode(np.fromfile(newPath,dtype=np.uint8),-1)

        #图片二值化处理，把[200,200,200]-[250,250,250]以外的颜色变成0
        thresh = cv2.inRange(imgSY,np.array([200,200,200]),np.array([250,250,250]))
        kernel = np.ones((3,3),np.uint8)
        #扩展待修复区域
        hi_mask = cv2.dilate(thresh,kernel,iterations=10)
        specular = cv2.inpaint(imgSY,hi_mask,5,flags=cv2.INPAINT_TELEA)
        cv2.imwrite(newPath, specular)

        #覆盖图片
        imgSY = Image.open(newPath)
        img = Image.open(image_path)
        img.paste(imgSY, (int(width*0.7),int(hight*0.8),width,hight))
        img.save(newPath)
        
        newPath = Path(newPath).resolve()
        return str(newPath) # 返回裁剪水印之后的图像绝对路径
    except Exception as e:
        print(f"处理图像时出错: {e}")
        return ''

def base64_to_image(base64_string):
    # Remove the prefix "data:image/png;base64,"
    base64_data = base64_string.split(",")[-1]
    img_data = base64.b64decode(base64_data)
    img = Image.open(io.BytesIO(img_data))
    return img


def content_postprocess(contents):
    # 对content进行清洗，去掉话题#/@/..的微博视频等
    content_list = contents.split("\n")
    for content in content_list:
        if not content:
            continue
        content = content.replace("#", "").replace('*','')
    return




# 调用deepseek时，可能遇到的错误码
DS_ERROR_CODES = {
    400:{"原因":"请求格式错误","解决办法":"请根据错误信息提示修改请求体"},
    401:{"原因":"API key 错误，认证失败","解决办法":"请检查您的 API key 是否正确，如没有 API key,请前往 https://api-docs.deepseek.com/ 创建API key"},
    402:{"原因":"账号余额不足","解决办法":"请确认账户余额，并前往 https://api-docs.deepseek.com/ 充值页面进行充值"},
    422:{"原因":"请求体参数错误","解决办法":"请根据错误信息提示修改相关参数"},
    429:{"原因":"请求速率（TPM 或 RPM）达到上限","解决办法":"请合理规划您的请求速率"},
    500:{"原因":"服务器内部故障","解决办法":"请等待后重试。若问题一直存在，请联系DeepSeek解决"},
    503:{"原因":"服务器负载过高","解决办法":"请稍后重试您的请求"}
}


# CHARACTER = [
#   '你是一位30岁的社交媒体博主，精通自媒体运营，擅长带节奏。在你的作品中，网络流行语丰富，标题党风格明显，煽动性强。语气轻松活泼，喜欢使用夸张语气词。例如：OMG！你绝对想不到，这款产品居然这么好用？！赶紧来看看我的深度测评，不看后悔一辈子！'  
# ]
from opencc import OpenCC
def convert_to_traditional(content):
    cc = OpenCC('s2tw')
    return cc.convert(content)



def read_data_from_txt(path):
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as file:
            result = [line.strip() for line in file.readlines() if line.strip()]
        return result
    else:
        return []
    

def read_mdfile(extract_path,image=False):
    keywords = []
    md_files = [f for f in os.listdir(extract_path) if f.endswith('_en.md')]
    if md_files:
        if not image:
            md_file = os.path.join(extract_path, md_files[0])  # 取第一个md文件路径
            with open(md_file, 'r', encoding='utf-8') as file:
                lines = file.readlines()
                for line in lines[:20]:
                    if line.strip() and line.strip()[0].isdigit():
                        keyword = line.strip().split('.')[-1]
                        keywords.append(keyword.strip())

            return keywords
        if image:
            md_file = os.path.join(extract_path, md_files[0])  # 取第一个md文件路径
            folder_name = extract_path.split('/')[-1].split('\\')[-1]
            pic_folder = os.path.join(extract_path, folder_name + '-pic')
            with open(md_file, 'r', encoding='utf-8') as file:
                lines = file.readlines()
                for line in lines[:20]:
                    if line.strip() and line.strip()[0].isdigit():
                        id = line.strip().split('.')[0]
                        image_file = None
                        for ext in ['.jpg', '.png', '.jpeg', '.gif']:
                            candidate = os.path.join(pic_folder, f"{id}{ext}")
                            if os.path.exists(candidate):
                                image_file = [candidate]
                                break
                        keyword = line.strip().split('.')[-1]
                        if  image_file is not None:  # 如果没找到图片则为 None ,只返回有图像的论文信息
                            keywords.append({
                            "keyword": keyword,
                            "image": image_file  
                        })
                return keywords
            



def split_think_and_answer(text: str):
    '''处理qwen3-32b思考模式的内容，返回think和answer'''
    m = re.search(r'<think\s*>(.*?)</think\s*>', text, flags=re.IGNORECASE|re.DOTALL)
    if not m:
        return None, text.strip()
    think = m.group(1).strip()
    answer = text[m.end():].strip()
    return think, answer


def parse_subject_and_content(text):
    # 1) 统一换行
    t = text.replace("\r\n", "\n").replace("\r", "\n")

    m = re.search(r'(?im)^\s*subject\s*:\s*(.+?)\s*$', t)
    subject = m.group(1).strip() if m else ""

    if m:
        start = m.end()
        rest = t[start:]
        # 去掉紧随其后的空行
        rest = re.sub(r'^\s*\n+', '', rest)
        content = rest.strip()
    else:
        # 没有 Subject 行时，全部当正文
        content = t.strip()

    return subject, content
