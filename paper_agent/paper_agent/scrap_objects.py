import os
import sys 
pythonpath = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0,pythonpath)
from utils.log import logger
from utils.sql import sql_dataset
from datetime import datetime,timedelta
import json
import random
import time
import pdb
import asyncio
from concurrent.futures import ThreadPoolExecutor
from utils.utils import convert_time_us
from utils.generation import *
from utils.prompt import generate_paper_keywords_prompt, generate_domain_keywords_prompt,filter_interest_domain_prompt,generate_paper_relativity_prompt
from bs4 import BeautifulSoup
import requests
import pdb
import re
from twitter_agent.twitter_bot import TwitterBot
from update_characters.extract_portrait import AccountPortrait

'''
1、从arxiv爬取target paper 的摘要，根据摘要提取关键词。
2、针对domain提取关键词
'''

class ScrapObjects():
    def __init__(self,log_path='./logs/paperagent/scrap_paper/scrap_paper_log.log'):
        self.log_path = log_path
        self.log = logger(filename=self.log_path)
        self.database = sql_dataset('papers')  # 论文数据库



    async def scrap_arxiv(self,title: str=None,domain:str=None) -> dict:
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

        # 5. 关键词（arxiv没有专门的关键词字段，通常在subjects里）
        # subject_tag = result.find("span", class_="tag is-small is-link tooltip is-tooltip-top")
        # keywords = subject_tag.text.strip() if subject_tag else None

        # LLM生成论文关键字
        try_num  =  0
        while try_num < 5:
            response = await general_generation([{"role":"system","content":generate_paper_keywords_prompt()},{"role":"user","content":abstract}]) # 32B
            if not response:
                try_num += 1
                continue
            else:
                keywords = response.split(',')
                self.log.info(f'生成的论文关键字是：{keywords}')
                break
        return {"Title": found_title,"Abstract": abstract,"URL": paper_url,"Gene_keywords": keywords,"Authors":authors}



    async def get_target_person_by_keywords(self,bot,account_id,keywords:list,domain:str=None):
        '''根据 domain 生成keywords，然后根据keywords去检索相关/潜在感兴趣的账号，形成一个 操作对象的集合'''
        # bot = TwitterBot()
        target_persons  = []
        for keyword in keywords: 
            if os.path.exists(f'./information/paperagent/target_persons/{domain}/{keyword}_persons.json'):
                with open(f'./information/paperagent/target_persons/{domain}/{keyword}_persons.json','r',encoding='utf-8') as f:
                    lines = f.readlines()
                    all_keyword_persons = [obj for line in lines if (obj := json.loads(line))]
                    target_persons.extend(all_keyword_persons)
                    continue
            else:
                all_keyword_pesons =  await bot.get_persons_by_keyword(account_id=account_id,keyword=keyword)   # 根据关键词检索用户
                all_keyword_pesons = json.loads(all_keyword_pesons.body.decode()).get("response") 
                if isinstance(all_keyword_pesons,list):
                    self.log.info(f'根据关键词{keyword}检索到的账号为{all_keyword_pesons}')  
                if isinstance(all_keyword_pesons,str):
                    self.log.error(f'根据关键词{keyword}检索相关账号失败')
                    continue
                # 根据用户的简介判断用户是否对 domain 感兴趣，感兴趣的话就添加到操作对象的集合中
                # 先写入文件
                os.makedirs(f'./information/paperagent/target_persons/{domain}/',exist_ok=True)
                for person_info in all_keyword_pesons:
                    try_num = 0
                    while try_num < 5:
                        response = await general_generation([{"role":"system","content":filter_interest_domain_prompt(domain)},{"role":"user","content":person_info["user_description"]}])
                        # response,_= await generation_post(text=filter_interest_domain_prompt(person_info["user_description"],domain),model="Qwen2.5-14b-Instruct")  # 14B
                        if not response:
                            self.log.error(f'用户 {person_info["url"]} 对 {domain} 感兴趣判断失败')
                            try_num += 1
                            continue
                        if '是' in response:
                            self.log.info(f'用户 {person_info["url"]} 对 {domain} 感兴趣')
                            # 添加到集合中并存储到数据库中
                            target_persons.append(person_info)
                            # 存储到数据库中（先写到文件中）
                            with open(f'./information/paperagent/target_persons/{domain}/{keyword}_persons.json','a', encoding='utf-8') as f:
                                f.write(json.dumps(person_info, ensure_ascii=False)+'\n')
                        elif '否' in response:
                            self.log.info(f'用户 {person_info["url"]} 对 {domain} 不感兴趣')
                        break
            
            if not os.path.exists(f'./information/paperagent/target_communities/{domain}/{keyword}_communities.json'):
                # 写入空内容
                with open(f'./information/paperagent/target_persons/{domain}/{keyword}_persons.json','a', encoding='utf-8') as f:
                        f.write(json.dumps({}, ensure_ascii=False)+'\n')              
                            
        return target_persons
    


    async def get_target_posts_by_keywords(self,bot,account_id,keywords:list,domain:str=None):   # Large Language Models for Recommendation
        '''
        根据domain 生成keywords，然后根据keywords去检索相关/潜在感兴趣的账号/帖子/社区，形成一个 操作对象的集合
        domain: target domain
        '''
        current_date = datetime.now().strftime("%Y-%m-%d")
        all_posts_info = []
        for keyword in keywords: 
            if os.path.exists(f'./information/paperagent/target_posts/{domain}/{keyword}/posts_{current_date}.json'):
                with open(f'./information/paperagent/target_posts/{domain}/{keyword}/posts_{current_date}.json','r',encoding='utf-8') as f:
                    lines = f.readlines()
                    all_keyword_posts = [json.loads(line) for line in lines]
                    all_posts_info.extend(all_keyword_posts)
            else:
                # all_keyword_posts = await bot.get_keyword_contents(account_id,keyword,num=15,time_limit=1)   # 根据关键词检索帖子,时间限制是1天前
                all_keyword_posts = await bot.scrap_content(account_id,keyword=keyword,num=15,time_limit=1) 
                all_keyword_posts = json.loads(all_keyword_posts.body.decode()).get("response") 
                time.sleep(2)
                if isinstance(all_keyword_posts,list):
                    self.log.info(f'根据关键词{keyword}检索到的帖子为{all_keyword_posts}')
                    # all_posts_info.extend(all_keyword_posts)
                if isinstance(all_keyword_posts,str):
                    self.log.error(f'根据关键词{keyword}检索相关帖子失败')
                    continue

                # 提取每个帖子的观点和话题，不需要抽取主要话题和观点
                posts_topic_data = await self.extract_interest_topic_view(data_info=all_keyword_posts,key='topic',extract_main=False)  
                posts_view_data = await self.extract_interest_topic_view(data_info=all_keyword_posts,key='view',extract_main=False) 
                map2 = {d['note_url']:d for d in posts_view_data}
                for d in posts_topic_data:
                    d['view'] = map2.get(d['note_url'],{}).get('view',[])
                all_posts_info.extend(posts_topic_data)

                # 先写入文件
                os.makedirs(f'./information/paperagent/target_posts/{domain}/{keyword}/',exist_ok=True)
                # 将目标帖子写到文件中（存入数据库中）
                for post_info in all_keyword_posts:
                    with open(f'./information/paperagent/target_posts/{domain}/{keyword}/posts_{current_date}.json','a', encoding='utf-8') as f:
                        f.write(json.dumps(post_info, ensure_ascii=False)+'\n')
                time.sleep(random.uniform(3,10))
        return all_posts_info    # 返回所有的帖子信息
    

    async def get_target_communities_by_keywords(self,bot,account_id,keywords:list,domain:str=None):   # Large Language Models for Recommendation
        '''
        根据domain 生成keywords，然后根据keywords去检索相关/潜在感兴趣的账号/帖子/社区，形成一个 操作对象的集合
        domain: target domain
        检索相关的社区，并根据社区的简介来判断 是否感兴趣
        '''
        
        # bot = TwitterBot()
        target_communities = []
        for keyword in keywords: 
            keyword = keyword.lower()
            if os.path.exists(f'./information/paperagent/target_communities/{domain}/{keyword}_communities.json'):
                with open(f'./information/paperagent/target_communities/{domain}/{keyword}_communities.json','r',encoding='utf-8') as f:
                    lines = f.readlines()
                    all_keyword_communities = [obj for line in lines if (obj := json.loads(line))]
                    target_communities.extend(all_keyword_communities)
                    continue
            else:
                all_keyword_communities = await bot.get_communities_by_keyword(account_id,keyword,num=20)   # 根据关键词检索社区，检索个数是30个
                all_keyword_communities = json.loads(all_keyword_communities.body.decode()).get("response") 
                if isinstance(all_keyword_communities,list) and len(all_keyword_communities) > 0:
                    self.log.info(f'根据关键词{keyword}检索到的社区信息为{all_keyword_communities}')
                elif isinstance(all_keyword_communities,str):
                    self.log.error(f'根据关键词{keyword}检索相关相关社区失败')
                    continue
                elif isinstance(all_keyword_communities,list) and len(all_keyword_communities) == 0:
                    self.log.info(f'根据关键词{keyword}检索到的社区信息为空')
                    # 文件内容写入空内容
                    with open(f'./information/paperagent/target_communities/{domain}/{keyword}_communities.json','a', encoding='utf-8') as f:
                        f.write(json.dumps({}, ensure_ascii=False)+'\n')
                    continue

            # 根据社区的简介判断该社区是否对 domain 感兴趣，感兴趣的话就添加到操作对象的集合中
            os.makedirs(f'./information/paperagent/target_communities/{domain}/',exist_ok=True)
            for community_info in all_keyword_communities:
                if community_info["community_description"] is None or community_info["community_description"] == '':
                    continue
                try_num = 0
                while try_num < 5:
                    response = await general_generation([{"role":"system","content":filter_interest_domain_prompt(domain)},{"role":"user","content":community_info["community_description"]}])
                    # response,_= await generation_post(text=filter_interest_domain_prompt(community_info["community_description"],domain),model="Qwen2.5-14b-Instruct")  # 14B 
                    if not response:
                        self.log.info(f'社区 {community_info["community_name"]} 对 {domain} 感兴趣判断失败')
                        try_num += 1
                        continue
                    if '是' in response:
                        self.log.info(f'社区 {community_info["community_name"]} 对 {domain} 感兴趣')
                        target_communities.append(community_info)
                        with open(f'./information/paperagent/target_communities/{domain}/{keyword}_communities.json','a', encoding='utf-8') as f:
                            f.write(json.dumps(community_info, ensure_ascii=False)+'\n')
                    elif '否' in response:
                        self.log.info(f'社区 {community_info["community_name"]} 对 {domain} 不感兴趣')
                    break       
        return target_communities    # 返回所有对domain感兴趣的社区



    async def get_object_paper_relativity(self,data_info:list,paper_info:dict=None):
        '''
        针对 操作对象集合，得到一些描述性 的sentence/keywords,来计算和target paper的相关性，并得到一个排序
        对于帖子来说，提取帖子中所表达的话题、观点
        对于人来说，使用description+贴文 提取话题、观点、和兴趣
        对于社区来说，提取话题、观点

        - data_info: list，帖子信息/用户信息
        - key_list: list，关键字列表，提取兴趣、观点、话题 

        根据每个帖子话题和观点，每个用户的兴趣和观点，计算和target paper的相关性,并进行排序，返回排序后的结果
        - data_info: list，帖子信息/用户信息/社区信息,三者的合并信息
        - paper_info: dict，论文信息，包括关键词、标题、摘要、作者等
        
        - return: list，排序后的结果
        '''
        # 提取data_info中的兴趣、观点、话题
        # 计算data_info和paper_info的相关性
        # 返回排序后的结果
        # pdb.set_trace()
        paper_keywords = ','.join(paper_info["Gene_keywords"])  # 论文的关键字
        for object_info in data_info:
            interest_keywords = object_info.get('interest', []) or []
            if isinstance(interest_keywords, str):   # 如果是字符串，就包装成列表
                interest_keywords = [interest_keywords]
            view_keywords = [item.get('opinion', '') for item in object_info.get('view', []) if item.get('opinion')]
            topic_keywords = object_info.get('topic', []) or []
            if isinstance(topic_keywords, str): # 如果是字符串，就包装成列表
                topic_keywords = [topic_keywords]
            all_keywords = [kw for kw in interest_keywords + view_keywords + topic_keywords if kw]
            if len(all_keywords) ==  0:
                object_info["score"] = 0
                continue
            object_keywords = ','.join(all_keywords)

            try_num  = 0
            while try_num < 5:
                response = await general_generation([{"role":"system","content":generate_paper_relativity_prompt(paper_keywords)},{"role":"user","content":object_keywords}])
                if not response:
                    try_num  += 1
                    continue
                object_info["score"] = float(response)
                break
            self.log.info(f'{object_info} 和 论文{paper_info["Title"]}的评分结果是：{response}')
        

        # 按score从高到低排序
        data_info_sorted = sorted(data_info, key=lambda x: x.get("score", 0), reverse=True)
        
        return data_info_sorted
    
    
    async def extract_interest_topic_view(self,data_info:list,key:str,extract_main:bool=True,key_list:list=None):
        '''提取每一个帖文中表达的兴趣，进行聚类，得到主要的兴趣'''
        e = AccountPortrait(data=data_info,interest_list=key_list)   # 使用domain关键字来提取帖子中的话题和观点
        await e.generate_key(key = key)      # 提取每一条贴文的兴趣/观点
        self.log.info(f'对每条贴文提取出来的{key}是：{e.data}')
        if extract_main:
            # 进行聚类，得到主要的兴趣
            mainly_result = await e.extract_main_key(key=key)  # 得到[str]
            self.log.info(f'提取出来的主要{key}是：{mainly_result}')
            return mainly_result  # 得到的带有兴趣的结果。
        else:
            return e.data

   


    async def get_object_set(self,account_id,paper_info:dict,domain:str,posts=True,persons=True,communities=True):
        '''
        根据target_paper和target_domain，得到操作对象集合，包括感兴趣的人、帖子、社区

        -account_id：要登陆的账号id
        -domain: target_domain
        -paper_info: dict， 论文的信息，包括title,abstract,url,keywords
        -posts: bool， 是否检索相关帖子,默认是True
        -persons: bool，是否检索相关账户,默认是True
        -communities: bool，是否检索相关社区,默认是True

        '''


        try_num = 0
        while try_num < 5:
            response = await general_generation([{"role":"system","content":generate_domain_keywords_prompt(language='英文')},{"role":"user","content":domain}]) # 32B
            # response,_ = await generation_post(text=generate_domain_keywords_prompt(domain=domain,language='英文'),language='英文',style='formal',model="Qwen2.5-14b-Instruct")  # 14B
            if not response:
                try_num += 1
                continue
            keywords = response.split(',')
            # LLM4Rec的关键词生成
            keywords = ['recommender systems', ' large language models', ' sequential recommendation', ' context-aware recommendation', ' cross-modal recommendation']
            break
        self.log.info(f'针对 {domain} 生成的关键词为{keywords}')  
            


        posts_info = []
        persons_info = []
        communities_info = []

        bot = TwitterBot(log_path = self.log_path)
        current_date = datetime.now().strftime("%Y-%m-%d")
        
        if posts:
            # 检索相关帖子
            all_posts_info = await self.get_target_posts_by_keywords(bot=bot,account_id=account_id,keywords=keywords,domain=domain)  # 根据关键字检索相关的帖子
            self.log.info(f'和{domain}相关的帖子是：{all_posts_info}')
            time.sleep(random.uniform(5,10))
            posts_info = all_posts_info
            # 提取每个帖子的观点和话题，不需要抽取主要话题和观点
            # posts_topic_data = await self.extract_interest_topic_view(data_info=all_posts_info,key='topic',extract_main=False)  
            # posts_view_data = await self.extract_interest_topic_view(data_info=all_posts_info,key='view',extract_main=False) 
            # map2 = {d['note_url']:d for d in posts_view_data}
            # for d in posts_topic_data:
            #     d['view'] = map2.get(d['note_url'],{}).get('view',[])
            # posts_info = posts_topic_data
            # self.log.info(f'获取和{domain}相关的每个帖子的观点和话题分别是：{posts_info}')
        bot.scroll(duration=random.uniform(5,10))
        if persons:  # 检索目标账号
            # 根据关键字获取目标账号
            all_persons_info = await self.get_target_person_by_keywords(bot=bot,account_id=account_id,keywords=keywords,domain=domain)  # 根据关键字检索相关的用户
            self.log.info(f'和{domain}相关的用户是：{all_persons_info}')
            time.sleep(random.uniform(5,10))

            # 获取每个用户的近五日发文，然后提取该用户的主要兴趣和主要关注话题
            if len(all_persons_info) != 0:
                self.log.info(f'获取和{domain}相关的10个用户近五日贴文动态')
                all_persons_info = random.sample(all_persons_info,10) if len(all_persons_info) >10 else all_persons_info # 随机选择10个用户
                for person_info in all_persons_info:
                    time.sleep(random.uniform(5,10))
                    scrap_response = await bot.scrap_content(account_id=account_id,url=person_info['url'],time_limit=5)  # 获取该用户5天之内的帖子，从而进行操作 
                    scrap_posts = json.loads(scrap_response.body.decode()).get("response") 
                    if not isinstance(scrap_posts, list) or not scrap_posts:
                        self.log.info(f'获取{person_info["url"]}近五日的贴文失败或为空')
                        continue
                    self.log.info(f'{person_info["url"]}近五日的贴文是：{scrap_posts},开始提取该用户的主要兴趣和主要话题')
                    person_info['interest'] = await self.extract_interest_topic_view(data_info = scrap_posts,key='interest', key_list = keywords,  extract_main=True) # 提取主要兴趣
                    person_info['topic'] = await self.extract_interest_topic_view(data_info = scrap_posts, key='topic', extract_main=True)   # 提取主要话题
                    person_info['posts'] = scrap_posts   # 保留每个 person 的 近五日贴文信息并返回
                    persons_info.append(person_info)

                    
            self.log.info(f'获取和{domain}相关的每个用户的主要兴趣和主要话题分别是：{persons_info}')
       
        bot.scroll(duration=random.uniform(5,10))
        if communities:   
            # 根据关键字检索相关的社区，并得到社区主要的话题和观点
            all_communities_info = await self.get_target_communities_by_keywords(bot=bot,account_id=account_id,keywords=keywords,domain=domain)   
            all_communities_info = random.sample(all_communities_info, min(10, len(all_communities_info)))   # 选择10个社区进行操作
            for community_info in all_communities_info:
                community_info["interest"] = community_info.get("community_description")   # 将社区的des作为interest
            communities_info = all_communities_info
            # 社区的帖子可以每次推荐论文的时候都爬取更新 
            

        # 关闭driver
        bot.driver.quit()
        time.sleep(random.uniform(3,8))

            
        # persons_info,账号的信息
        # posts_info,帖子的信息
        # communities_info.社区的信息

        # 和 paper的abstract 做相似度计算，进行相似度的打分
        if not persons_info and not posts_info and not communities_info:
            self.log.info(f'没有找到和{domain}相关的用户、帖子、社区')
            return [] 
        sorted_results = await self.get_object_paper_relativity(data_info = persons_info+posts_info+communities_info,paper_info = paper_info)
        self.log.info(f'按照和paper的相关性, 从高到低的排序得到的结果是:  {sorted_results}')
        # 存入文件中
        os.makedirs(f'./information/paperagent/{current_date}/',exist_ok=True)
        for result in sorted_results:
            with open(f'./information/paperagent/{current_date}/{paper_info["Title"]}_object_set.json','a',encoding='utf-8') as f:
                f.write(json.dumps(result, ensure_ascii=False)+'\n')
        self.log.info(f'将按照相关性排序后的操作对象已写入文件')
        return sorted_results  # 返回所有可操作对象集合 和相关用户近五日的贴文



    


if __name__ == '__main__':
    agent = ScrapObjects()
    asyncio.run(agent.get_object_set(account_id=224,domain='LLM4Rec',persons=False,paper_title='The Best is Yet to Come: Graph Convolution in the Testing Phase for Multimodal Recommendation'))

    # persons_info =  [{'url': 'https://x.com/DecentralGPT', 'nickname': 'DecentralGPT', 'user_description': 'DecentralGPT is a decentralized AI large language model inference network. Telegram: https://t.me/DecentralGPT https://degpt.ai', 'interest': ['LLMs, ML, Neural Networks, Optimization, Evaluation, Scalability, Engagement, Privacy, Diversity, Fairness, Explainability.'], 'topic': ['AI advancements by OpenAI, NVIDIA, AMD; emergence of decentralized AI models like DecentralGPT, Web3AI.']}]
    # posts_info = [{'nickname': 'MetalRabbit13X', 'user_url': 'https://x.com/MetalRabbit13X', 'note_url': 'https://x.com/MetalRabbit13X/status/1955446667689537561', 'note_form': '文字', 'note_type': '原创', 'post_time_ip': '2025-08-13T01:49:50.000Z', "title": '', 'content': 'When #AI lacks discernment: study reveals #cognitivebiases in lg language models\n#Chatbots can b maddeningly confident—yet they’ll ditch correct ans at the 1st nudge. That’s dangerous when u need reliable advice. A new arXiv paper from Google DeepMind…', 'transmits': 0, 'views': '9', 'comments': 0, 'bookmarks': 0, 'likes': 0, 'images_url': [], 'keyword': 'Large Language Models', 'topic': ['AI', ' cognitive biases', ' language models', ' chatbots', ' reliable advice', ' Google DeepMind'], 'view': [{'opinion': 'AI lacks discernment', 'stand': '反对'}, {'opinion': 'cognitive biases in language models', 'stand': '反对'}]}, {'nickname': 'MetalRabbit13', 'user_url': 'https://x.com/MetalRabbit13', 'note_url': 'https://x.com/MetalRabbit13/status/1955445545583210854', 'note_form': '文字', 'note_type': '原创', 'post_time_ip': '2025-08-13T01:45:23.000Z', "title": '', 'content': 'When #AI lacks discernment: study reveals #cognitivebiases in lg language models\n#Chatbots can b maddeningly confident—yet they’ll ditch correct ans at the 1st nudge. That’s dangerous when u need reliable advice. A new arXiv paper from Google DeepMind &…', 'transmits': 0, 'views': '16', 'comments': 0, 'bookmarks': 0, 'likes': 0, 'images_url': [], 'keyword': 'Large Language Models', 'topic': ['AI', ' cognitive biases', ' language models', ' chatbots', ' reliable advice'], 'view': [{'opinion': 'AI lacks discernment', 'stand': '反对'}, {'opinion': 'cognitive biases in language models', 'stand': '反对'}]}, {'nickname': 'Game Theory Papers', 'user_url': 'https://x.com/DO', 'note_url': 'https://x.com/DO/status/1955433647374262574', 'note_form': '文字', 'note_type': '原创', 'post_time_ip': '2025-08-13T00:58:06.000Z', "title": '', 'content': 'Game Reasoning Arena: A Framework and Benchmark for Assessing Reasoning Capabilites of Large Language Models via Game Play.', 'transmits': 0, 'views': '19', 'comments': 0, 'bookmarks': 0, 'likes': 0, 'images_url': [], 'keyword': 'Large Language Models', 'topic': ['Game Reasoning Arena', ' Large Language Models', ' Reasoning Capabilities', ' Game Play Benchmark'], 'view': []}, {'nickname': 'AI Native Foundation', 'user_url': 'https://x.com/AINativeF', 'note_url': 'https://x.com/AINativeF/status/1955431946424836205', 'note_form': '图文', 'note_type': '原创', 'post_time_ip': '2025-08-13T00:51:20.000Z', "title": '', 'content': '13. Reinforcement Learning in Vision: A Survey\n\n Keywords: Visual Reinforcement Learning, Policy Optimization, Multi-Modal Large Language Models, Unified Model Frameworks, Visual Generation\n\n Category: Reinforcement Learning\n\n Research Objective:\n   - The primary goal is to provide a comprehensive synthesis of recent advancements in visual reinforcement learning, emphasizing policy optimization strategies and evaluating protocols, while identifying future challenges and promising research directions.\n\n Research Methods:\n   - The paper formalizes visual reinforcement learning problems, examines various policy optimization strategies, and organizes over 200 studies into four thematic pillars, which include multi-modal large language models, visual generation, unified model frameworks, and vision-language-action models. Key methods involve reviewing algorithmic designs, reward engineering, and various evaluation protocols.\n\n Research Conclusions:\n   - The survey identifies significant trends such as curriculum-driven training and preference-aligned diffusion, highlighting open challenges like sample efficiency, generalization, and safe deployment. It provides researchers with a coherent map of the landscape and suggestions for future research directions.\n\n Paper link: https://huggingface.co/papers/2508.08189…', 'transmits': 0, 'views': '32', 'comments': 0, 'bookmarks': 0, 'likes': 0, 'images_url': ['https://pbs.twimg.com/media/GyMW_h0aEAEU5G2?format=png&name=small'], 'keyword': 'Large Language Models', 'topic': ['Visual Reinforcement Learning', ' Policy Optimization', ' Multi-Modal Large Language Models', ' Unified Model Frameworks', ' Visual Generation'], 'view': [{'opinion': 'curriculum-driven training', 'stand': 'support'}, {'opinion': 'preference-aligned diffusion', 'stand': 'support'}, {'opinion': 'sample efficiency', 'stand': 'identify challenge'}, {'opinion': 'generalization', 'stand': 'identify challenge'}, {'opinion': 'safe deployment', 'stand': 'identify challenge'}]}, {'nickname': 'AI Native Foundation', 'user_url': 'https://x.com/AINativeF', 'note_url': 'https://x.com/AINativeF/status/1955431913629634642', 'note_form': '图文', 'note_type': '原创', 'post_time_ip': '2025-08-13T00:51:13.000Z', "title": '', 'content': '12. Temporal Self-Rewarding Language Models: Decoupling Chosen-Rejected via Past-Future\n\n Keywords: Temporal Self-Rewarding Language Models, Preference Learning, Out-of-Distribution Generalization, Large Language Models(LLMs), Direct Preference Optimization  \n\n Category: Generative Models  \n\n Research Objective:\n   - To improve generative capabilities by strategically using past and future outputs to enhance preference learning and generalization in Self-Rewarding Language Models.\n\n Research Methods:\n   - Introduced a dual-phase framework: (1) Anchored Rejection, (2) Future-Guided Chosen, applied across different model families and sizes such as Llama, Qwen, and Mistral.\n\n Research Conclusions:\n   - The proposed Temporal Self-Rewarding model yields significant improvements, demonstrating a 29.44 win rate on AlpacaEval 2.0, outperforming the baseline. It also shows superior out-of-distribution generalization in tasks like mathematical reasoning, QA, and code generation.\n\n Paper link: https://huggingface.co/papers/2508.06026…', 'transmits': 0, 'views': '5', 'comments': 0, 'bookmarks': 0, 'likes': 0, 'images_url': ['https://pbs.twimg.com/media/GyMW9m6bwAAEd8B?format=png&name=small'], 'keyword': 'Large Language Models', 'topic': ['Temporal Self-Rewarding Language Models', ' Preference Learning', ' Out-of-Distribution Generalization', ' Large Language Models', ' Direct Preference Optimization'], 'view': []}, {'nickname': 'AI Native Foundation', 'user_url': 'https://x.com/AINativeF', 'note_url': 'https://x.com/AINativeF/status/1955431884437295610', 'note_form': '图文', 'note_type': '原创', 'post_time_ip': '2025-08-13T00:51:06.000Z', "title": '', 'content': '11. Grove MoE: Towards Efficient and Superior MoE LLMs with Adjugate Experts\n\n Keywords: Grove MoE, large language models, heterogeneous experts, dynamic activation, computational efficiency\n\n Category: Natural Language Processing\n\n Research Objective:\n   - Introduce Grove MoE architecture to improve computational efficiency and performance in large language models through dynamic parameter activation based on input complexity.\n\n Research Methods:\n   - Utilize heterogeneous experts of varying sizes inspired by the big.LITTLE CPU architecture and apply an upcycling strategy during mid-training and post-training.\n\n Research Conclusions:\n   - Grove MoE models activate parameters dynamically, achieving performance comparable to state-of-the-art open-source models while expanding model capacity with manageable computational overhead.\n\n Paper link: https://huggingface.co/papers/2508.07785…', 'transmits': 0, 'views': '22', 'comments': 0, 'bookmarks': 0, 'likes': 0, 'images_url': ['https://pbs.twimg.com/media/GyMW79UaEAExTKJ?format=jpg&name=small'], 'keyword': 'Large Language Models', 'topic': ['Grove MoE', ' large language models', ' computational efficiency', ' heterogeneous experts', ' dynamic activation'], 'view': []}, {'nickname': 'AI Native Foundation', 'user_url': 'https://x.com/AINativeF', 'note_url': 'https://x.com/AINativeF/status/1955431829466665003', 'note_form': '图文', 'note_type': '原创', 'post_time_ip': '2025-08-13T00:50:52.000Z', "title": '', 'content': "7. UserBench: An Interactive Gym Environment for User-Centric Agents\n\n Keywords: Large Language Models, UserBench, simulated users, task completion, user alignment\n\n Category: Human-AI Interaction\n\n Research Objective:\n   - The research aims to address the gap in LLM-based agents' ability to proactively collaborate with users, especially when users' goals are vague, evolving, or indirectly expressed.\n\n Research Methods:\n   - Introduction of UserBench, a user-centric benchmark designed for evaluating agents in multi-turn, preference-driven interactions with simulated users who start with underspecified goals.\n\n Research Conclusions:\n   - Evaluation reveals a significant disconnect between task completion and user alignment, with models aligning fully with user intents only 20% of the time.\n   - Even advanced models uncover fewer than 30% of all user preferences through active interaction, highlighting the challenges in developing true collaborative partners.\n\n Paper link: https://huggingface.co/papers/2507.22034…", 'transmits': 0, 'views': '13', 'comments': 0, 'bookmarks': 0, 'likes': 0, 'images_url': ['https://pbs.twimg.com/media/GyMW4vdaUAA5WTb?format=jpg&name=small'], 'keyword': 'Large Language Models', 'topic': ['Large Language Models', ' UserBench', ' simulated users', ' task completion', ' user alignment'], 'view': []}, {'nickname': 'AI Native Foundation', 'user_url': 'https://x.com/AINativeF', 'note_url': 'https://x.com/AINativeF/status/1955431803428418024', 'note_form': '图文', 'note_type': '原创', 'post_time_ip': '2025-08-13T00:50:46.000Z', "title": '', 'content': '5. BrowseComp-Plus: A More Fair and Transparent Evaluation Benchmark of Deep-Research Agent\n\n Keywords: AI-generated, deep-research agents, large language models, retrieval methods, controlled experimentation\n\n Category: Natural Language Processing\n\n Research Objective:\n   - The paper introduces BrowseComp-Plus, a curated benchmark that allows for controlled evaluation of deep-research agents and retrieval methods to gain insights into their performance and effectiveness.\n\n Research Methods:\n   - BrowseComp-Plus leverages a fixed, carefully curated corpus with human-verified supporting documents and challenging negatives for controlled experimentation. It distinguishes performance differences using various retrieval models.\n\n Research Conclusions:\n   - The benchmark effectively differentiates deep research system performance, showing significant improvements in accuracy when integrating GPT-5 with Qwen3-Embedding-8B, demonstrating the importance of retrieval effectiveness and citation accuracy.\n\n Paper link: https://huggingface.co/papers/2508.06600…', 'transmits': 0, 'views': '9', 'comments': 0, 'bookmarks': 0, 'likes': 0, 'images_url': ['https://pbs.twimg.com/media/GyMW3OPaIAAkJvU?format=png&name=small'], 'keyword': 'Large Language Models', 'topic': ['AI-generated', ' deep-research agents', ' large language models', ' retrieval methods', ' controlled experimentation'], 'view': [{'opinion': 'BrowseComp-Plus allows for controlled evaluation', 'stand': '支持'}, {'opinion': 'GPT-5 with Qwen3-Embedding-8B improves accuracy', 'stand': '支持'}]}, {'nickname': 'AI Native Foundation', 'user_url': 'https://x.com/AINativeF', 'note_url': 'https://x.com/AINativeF/status/1955431703046226305', 'note_form': '图文', 'note_type': '原创', 'post_time_ip': '2025-08-13T00:50:22.000Z', "title": '', 'content': '2. WideSearch: Benchmarking Agentic Broad Info-Seeking\n\n Keywords: WideSearch, Large Language Models, benchmark, agentic search systems, quality control pipeline\n\n Category: AI Systems and Tools\n\n Research Objective:\n   - To introduce WideSearch, a new benchmark for evaluating the reliability of automated search agents in large-scale information collection tasks, highlighting significant deficiencies in current systems.\n\n Research Methods:\n   - Developed a benchmark with 200 curated questions across 15 domains.\n   - Established a five-stage quality control pipeline to ensure dataset difficulty, completeness, and verifiability.\n   - Evaluated over 10 state-of-the-art search systems, including single-agent, multi-agent frameworks, and end-to-end commercial systems.\n\n Research Conclusions:\n   - Present search agents exhibit critical deficiencies in handling large-scale information seeking, with success rates near 0%, while human testers achieve near 100% success rates with sufficient time and cross-validation.\n   - The findings indicate urgent areas for future research and development in agentic search systems.\n\n Paper link: https://huggingface.co/papers/2508.07999…', 'transmits': 0, 'views': '8', 'comments': 0, 'bookmarks': 0, 'likes': 0, 'images_url': ['https://pbs.twimg.com/media/GyMWxYyaEAI1Vyc?format=jpg&name=small'], 'keyword': 'Large Language Models', 'topic': ['WideSearch', ' Large Language Models', ' benchmark', ' agentic search systems', ' quality control pipeline'], 'view': [{'opinion': 'WideSearch benchmark highlights deficiencies in current search agents', 'stand': '支持'}]}, {'nickname': 'mouhoun said', 'user_url': 'https://x.com/saidmouhoun', 'note_url': 'https://x.com/saidmouhoun/status/1955430145621479826', 'note_form': '文字', 'note_type': '原创', 'post_time_ip': '2025-08-13T00:44:11.000Z', "title": '', 'content': "I went down a rabbit hole this week trying to understand why a small tweak in transformer architectures called SwiGLU works so well in large language models.\nI really didn't expect what I found at the end.", 'transmits': 0, 'views': '4', 'comments': 0, 'bookmarks': 0, 'likes': 0, 'images_url': [], 'keyword': 'Large Language Models', 'topic': ['SwiGLU', ' transformer architectures', ' large language models'], 'view': []}]
    # paper_info = {"title": 'The Best is Yet to Come: Graph Convolution in the Testing Phase for Multimodal Recommendation', 'abstract': "The efficiency and scalability of graph convolution networks (GCNs) in training recommender systems remain critical challenges, hindering their practical deployment in real-world scenarios. In the multimodal recommendation (MMRec) field, training GCNs requires more expensive time and space costs and exacerbates the gap between different modalities, resulting in sub-optimal recommendation accuracy. This paper critically points out the inherent challenges associated with adopting GCNs during the training phase in MMRec, revealing that GCNs inevitably create unhelpful and even harmful pairs during model optimization and isolate different modalities. To this end, we propose FastMMRec, a highly efficient multimodal recommendation framework that deploys graph convolutions exclusively during the testing phase, bypassing their use in training. We demonstrate that adopting GCNs solely in the testing phase significantly improves the model's efficiency and scalability while alleviating the modality isolation problem often caused by using GCNs during the training phase. We conduct extensive experiments on three public datasets, consistently demonstrating the performance superiority of FastMMRec over competitive baselines while achieving efficiency and scalability.\n        △ Less", 'paper_url': 'https://arxiv.org/abs/2507.18489', 'keywords': ['graph convolution networks', ' GCNs', ' multimodal recommendation', ' MMRec', ' efficiency', ' scalability', ' model optimization', ' modality isolation', ' FastMMRec', ' testing phase', ' recommendation accuracy', ' public datasets', ' competitive baselines']}
    # sorted_results = asyncio.run(agent.get_object_paper_relativity(data_info = persons_info+posts_info,paper_info = paper_info))
    # print(f'按照和paper的相关性, 从高到低的排序得到的结果是:  {sorted_results}')

    # post: note_url
    # person: url
    # community :community_url
