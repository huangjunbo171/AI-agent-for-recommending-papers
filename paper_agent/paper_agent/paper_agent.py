import os
import sys 
pythonpath = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0,pythonpath)
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
from utils.utils import convert_time_us,read_mdfile,read_data_from_txt
from utils.generation import *
from utils.prompt import *
from bs4 import BeautifulSoup
import requests
import pdb
import re
from paper_agent.scrap_objects import ScrapObjects
import schedule
import multiprocessing
import asyncio
try:
    from paper_agent.prompts_test import *
except ModuleNotFoundError:
    from prompts_test import *
# 构造platform和bot/planner的映射。跨平台依赖按需导入，避免 Twitter 流程被 xhs/weibo 依赖阻塞。
def get_bot_class(platform: str):
    if platform == "twitter":
        return TwitterBot
    if platform == "xiaohongshu":
        from xhs_agent.xhs_bot import XiaohongshuBot
        return XiaohongshuBot
    raise ValueError(f"Unsupported platform: {platform}")


def get_planner_class(platform: str):
    if platform == "twitter":
        return TwitterPlanner
    if platform == "xiaohongshu":
        from xhs_agent.xhs_planner import XiaohongshuPlanner
        return XiaohongshuPlanner
    raise ValueError(f"Unsupported platform: {platform}")

class PaperAgent():
    def __init__(self,platform:str='twitter',log_path='./logs/paperagent/paper_log.log'):
        self.platform = platform
        self.log_path = log_path    
        self.log = logger(filename=self.log_path)
        self.database = sql_dataset(self.platform)
        self.paper_database = sql_dataset('papers')
        if self.platform == 'twitter':
            self.action_limits = {"点赞": 10, "转发": 10, "评论": 10, "快转": 5, "关注": 5}   # 操作上限
            self.language = '英文'
            self.max_length = 270
            self.posts =True
            self.persons=True
            self.communities=True
            self.auto_post=False # 主动发帖
        elif self.platform == 'xiaohongshu':
            self.action_limits = {"点赞": 10, "收藏": 10, "评论": 10, "关注": 5}   # 操作上限
            self.language = '中文'
            self.max_length = 300
            self.posts =False
            self.persons=False
            self.communities=False
            self.auto_post=True # 主动发帖

        self.action_alias = {"仅评论": "评论","仅转发": "转发"}  # 动作别称

    def _force_run_now_enabled(self):
        return os.environ.get("FORCE_RUN_NOW") == "1"

    def _runtime_limit_reached(self, start_ts, max_runtime_minutes):
        if max_runtime_minutes is None:
            return False
        return (time.monotonic() - start_ts) >= max_runtime_minutes * 60

    def format_action_time(self, action_times):
        """将{"id":[time]}转换为{"time":[id]}"""
        # 创建一个空字典用于存储 time: [id]
        time_to_ids = {}

        # 遍历列表中的每个字典
        for entry in action_times:
            for id_, times in entry.items():
                for time in times:
                    time = time.split(':')[0]
                    if time not in time_to_ids:
                        time_to_ids[time] = []  # 初始化一个空列表
                    time_to_ids[time].append(id_)  # 将id添加到对应时间的列表中

        # 按时间顺序排序字典
        sorted_time_dict = dict(sorted(time_to_ids.items()))
        return sorted_time_dict


    async def predict_action_time(self,account_id):
        self.log.info(f"输入的信息为account_id={account_id},开始预测账户{account_id}操作时间")
        action_time = []
        today = datetime.now()#.strftime("%Y-%m-%d %H:%M:%S")
        self.log.info(f"当前时间：{today}")
        for i in range(7):
            predict_time = (today + timedelta(days=i)).strftime("%Y-%m-%d")
            # response,_ = await  generation_post(text=GENERAL_PLAN,model="Qwen2.5-14b-Instruct")   # 14B
            response = await general_generation([{"role":"system","content":GENERAL_PLAN},{"role":"user","content":f'''{predict_time}'''}])
            self.log.info(f"预测的{predict_time}的活跃时间为：{response}")
            response = eval(response)
            # 一天只操作一次 
            # details = response["detail"]
            # if len(details) > 1:
            #         response["detail"] = random.sample(details,1)

            action_time.append(response)
        self.log.info(f"预测的未来一周的活跃时间为：{action_time}")
        sql = '''UPDATE accounts_info SET Prediction_Action_Time = %s WHERE Account_id = %s'''
        self.database.operation(sql,(json.dumps(action_time),account_id,))
        self.log.info(f'''预测到{account_id}的操作时间为：{action_time}''')
        return action_time
    


    async def get_action_time(self,account_ids,url=None,history=None,current_time=None,is_predict=True):
        accounts = []
        for account_id in account_ids:
            if account_ids.index(account_id) == 0:
                if is_predict:
                    planner = get_planner_class(self.platform)(log_path=f"./logs/{self.platform}/{account_id}/planner_log.log")
                    action_time = await planner.get_prediction_time(url=url,account_id=account_id,history=history)
                    self.log.info(f'''预测到{account_id}的操作时间为：{action_time}''')
                else:
                    search_sql = f"SELECT * FROM accounts_info WHERE accounts_info.Account_id = {account_id}"
                    result = self.database.get_dict_data_sql(search_sql)[0]
                    action_time = json.loads(result["Prediction_Action_Time"])
                date_time =current_time.strftime("%Y-%m-%d")
                for item in action_time:
                    if item["date"] == date_time:
                        accounts.append({f'{account_id}':item["detail"]})
                        break
            else:
                self.log.info(f'''预测到{account_id}的操作时间为：{action_time}''')
                # 更新数据库
                self.log.info(f"账号{account_id}预测的未来一周的活跃时间为：{action_time}")
                sql = '''UPDATE accounts_info SET Prediction_action_time = %s WHERE Account_id = %s'''
                self.database.operation(sql,(json.dumps(action_time),account_id,))
                self.log.info(f"更新数据库中账号{account_id}活跃时间成功")
                for item in action_time:
                    if item["date"] == date_time:
                        accounts.append({f'{account_id}':item["detail"]})
                        break
        self.log.info(f"获取到的账号操作时间为：{accounts}")
        
        return accounts



    # 多个账号串行执行操作,串行运营同一领域 的 多个账号
    async def auto_cultivation(self,account_ids:list,domain:str=None,paper_path=None,max_cycles=None,max_runtime_minutes=None):
        '''
        account_ids:要运营的账号
        domain: 目标领域
        model: 使用的模型，默认是Qwen3-32B
        posts: 是否检索相关帖子，默认是True
        persons: 是否检索相关人物，默认是True
        communities: 是否检索相关社区，默认是True
        paper_path: md论文的路径，md文件里的论文和account_ids一一对应，可以改成paper_title
        '''
        

        self.log.info(f'''开始培育账号:{account_ids}''')
        if self._force_run_now_enabled() and max_cycles is None:
            max_cycles = 1
        start_ts = time.monotonic()
        completed_cycles = 0

        # 每个账号要获取的 最新一条通知 的时间
        time_limit = convert_time_us(datetime.now()- timedelta(days=1)) # 第一次，获取3天前的通知
        accounts_notify_time = { account_id: time_limit for account_id in account_ids}   # 每个账号和它的time_limit
        self.log.info(f'账号的通知时间是：{accounts_notify_time}')

        while True:
            if self._runtime_limit_reached(start_ts, max_runtime_minutes):
                self.log.info(f'已达到最大运行时长 {max_runtime_minutes} 分钟，自动退出')
                break
            if max_cycles is not None and completed_cycles >= max_cycles:
                self.log.info(f'已达到最大运行轮次 {max_cycles}，自动退出')
                break
            # 确认每个账号的操作时间是否过期
            for account_id in account_ids:
                search_sql = f"SELECT * FROM accounts_info WHERE accounts_info.Account_id = {account_id}"
                result = self.database.get_dict_data_sql(search_sql)[0]
                self.log.info(f'''获取到的账号信息为：{result}''')
                current_time = convert_time_us(datetime.now())
                self.log.info(f'''当前时间为：{current_time}''')
                if result["Prediction_Action_Time"] is None:
                    accounts_time = await self.get_action_time(account_ids,current_time=current_time)
                else:
                    action_time = json.loads(result["Prediction_Action_Time"])
                    if current_time > datetime.strptime(action_time[-1]["date"], "%Y-%m-%d"):
                        accounts_time = await self.get_action_time(account_ids,current_time=current_time)
                    else:
                        accounts_time = await self.get_action_time(account_ids,current_time=current_time,is_predict=False)
            # 将账号时间规范化
            self.log.info(f'账号的操作时间是：{accounts_time}')
            # planner = TwitterPlanner(log_path=f"./logs/{self.platform}/{account_ids[0]}/{self.platform}_log.log")
            planner = get_planner_class(self.platform)(log_path=f"./logs/{self.platform}/{account_ids[0]}/{self.platform}_log.log")
            accounts_time = planner.fomat_action_time(accounts_time)    # {'05:30': ['1'], '07:15': ['2'], '14:30': ['2'], '20:30': ['1']} time:id
            self.log.info(f"规范化后的账号时间为：{accounts_time}") 
            
            while True:
                if self._runtime_limit_reached(start_ts, max_runtime_minutes):
                    self.log.info(f'已达到最大运行时长 {max_runtime_minutes} 分钟，自动退出')
                    return
                if max_cycles is not None and completed_cycles >= max_cycles:
                    self.log.info(f'已达到最大运行轮次 {max_cycles}，自动退出')
                    return
                now_time = datetime.now().strftime("%H:%M")
                now_time = '19:50'
                current_hour = now_time.split(":")[0]
                accounts_dict = {time:ids for time,ids in accounts_time.items() if time.split(":")[0] == current_hour}
                if not accounts_dict and self._force_run_now_enabled() and accounts_time:
                    first_time = next(iter(accounts_time.keys()))
                    accounts_dict = {first_time: accounts_time[first_time]}
                    self.log.info("FORCE_RUN_NOW=1，跳过排班等待，立即执行当前账号")
                self.log.info(f'''当前时间为：{now_time}，当前小时的操作账号为：{accounts_dict}''')
                if accounts_dict:
                    accounts =  list(set().union(*accounts_dict.values()))  # 所有的账号都集合到一个list中
                    for account_id in accounts:
                        '''读取数据库从数据库中选择一个未宣传过的论文进行宣传'''
                        # 读取数据库，从中找贴文进行宣传
                        select_sql = f'''SELECT pi.Paper_id, pi.Title, pi.Image_path, pi.URL FROM papers_info AS pi WHERE JSON_CONTAINS(pi.Field, JSON_QUOTE('{domain}'), '$') AND NOT EXISTS (SELECT 1 FROM papers_promotion AS pp WHERE pp.Paper_id  = pi.Paper_id AND pp.Platform  = '{self.platform}' AND pp.Account_id = {account_id}) ORDER BY pi.Paper_id;  '''
                        paper_results = self.paper_database.get_dict_data_sql(sql=select_sql)
                        if not paper_results:
                            self.log.info(f'数据库中不存在{domain}的相关论文')
                            return
                        # 随机选择一个domain领域的文章进行宣传
                        paper = random.choice(paper_results)
                        scrap_paper = ScrapObjects(log_path=f'./logs/paperagent/twitter/scrap_paper/{account_id}/scrap_paper_log.log')
                        paper_info = await scrap_paper.scrap_arxiv(title=paper['Title'],domain=domain)
                        paper_info['image_paths'] = [paper['Image_path']]  # 转换成list
                        paper_info['Paper_id'] = paper['Paper_id']
                        self.log.info(f'账号{account_id}要宣传的论文信息是：{paper_info}')
                        
                        # 初始化账号bot,获取操作对象、执行操作等
                        bot = get_bot_class(self.platform)(log_path=f"./logs/{self.platform}/{account_id}/{self.platform}_log.log")  
                        await bot.login_by_cookies(account_id=int(account_id))  # 登录账号
                        propaganda_results = await self.auto_paper_single_account(account_id=int(account_id),paper_info=paper_info,domain=domain,bot=bot)   # 账号运营
                        await asyncio.sleep(random.uniform(5,10))
                        if len(propaganda_results) !=  0 :
                            # 查询account_id的nickname
                            select_nickname = f'''SELECT Account FROM accounts_info WHERE Account_id = {account_id}'''
                            account_nickname = self.database.get_dict_data_sql(select_nickname)[0]['Account']
                            # 将宣传的链接存入到数据库中
                            insert_sql = '''INSERT INTO papers_promotion(`Paper_id`,`Platform`,`Account_id`,`Account`,`Post_URL`,`Update_time`) VALUES (%s,%s,%s,%s,%s,%s)'''
                            self.database.operation(insert_sql,(paper_info['Paper_id'],'twitter',account_id,account_nickname,json.dumps(propaganda_results),datetime.now()))
                            self.log.info(f'账号{account_id}宣传论文{paper_info["Title"]}的结果已经存入到数据库中')
                        # 获取通知、回复评论等内容
                        if self.platform == 'twitter':
                            accounts_notify_time[int(account_id)] = await self.get_notification_messages(account=int(account_id), time_limit=accounts_notify_time[int(account_id)],bot=bot) 
                        
                        if isinstance(accounts_notify_time[int(account_id)],str):
                            # 函数执行失败，结束 
                            self.log.info(f'账号{account_id}获取通知失败，结束')
                            bot.driver.quit()  # 关闭浏览器
                            continue 
                        elif isinstance(accounts_notify_time[int(account_id)],datetime):
                            self.log.info(f'账号{account_id}获取通知时间成功')
                        await asyncio.sleep(random.uniform(5,10))
                        bot.driver.quit()  # 关闭浏览器
                        self.log.info(f'账号{account_id}已经执行完所有操作，关闭该账号的driver')
                    self.log.info(f'账号{accounts}已经全部执行完操作，等待下一个时间点')
                    break
                else:
                    self.log.info('等待到达目标时间')
                    wait_seconds = random.uniform(150,300)
                    if max_runtime_minutes is not None:
                        remaining_seconds = max(0, max_runtime_minutes * 60 - (time.monotonic() - start_ts))
                        wait_seconds = min(wait_seconds, remaining_seconds)
                    if wait_seconds <= 0:
                        self.log.info(f'已达到最大运行时长 {max_runtime_minutes} 分钟，自动退出')
                        return
                    await asyncio.sleep(wait_seconds)
            completed_cycles += 1
            if max_cycles is not None and completed_cycles >= max_cycles:
                self.log.info(f'已达到最大运行轮次 {max_cycles}，自动退出')
                break

    # async def get_domain_keywords(self,domain:str):
    #     '''获取领域的关键字。对于新的领域，生成的关键字存到文件中'''
    #     # 同一个领域的领域关键字写入到文件中
    #     file_path = './information/paperagent/domain_keywords.json'
    #     with open(file_path,'r',encoding='utf-8') as f:
    #         lines = f.readlines()
    #         domains_name = [next(iter(json.loads(line.strip()))).lower() for line in lines if line.strip()]  # 全部转换为小写
    #         domains_keywords = [next(iter(json.loads(line.strip()).values())) for line in lines if line.strip()]
    #     if domain.lower() not in domains_name:
    #         # 获取领域关键字
    #         _,response = await general_generation_think([{"role":"system","content":generate_domain_keywords_prompt(language=self.language)},{"role":"user","content":domain}]) # 32B
    #         domain_keywords = response.split(',')
    #         self.log.info(f'生成的 {domain} 关键字是：{domain_keywords}')
    #         with open(file_path,'a',encoding='utf-8') as f:
    #             f.write(json.dumps({domain:domain_keywords},ensure_ascii=False) + '\n')  
    #     else:
    #         domain_keywords  = domains_keywords[domains_name.index(domain.lower())]
    #         self.log.info(f'{domain} 关键字是：{domain_keywords}')
            
    #     return domain_keywords



    async def auto_paper_single_account(self,account_id,paper_title:str=None,domain:str=None,paper_info:dict=None,bot=None):
        '''
        一个账号获取论文信息、获取目标集合，执行操作
        获取目标集合(三种类型，小红书平台没有社区)
            - 贴文：使用论文关键字检索，检索到相关帖子之后，使用论文的摘要来判断和论文是否相关，相关的话执行操作
            - 账号：从大v账号中随机选取几个进行交互
            - 社区：使用领域关键字检索社区，然后执行操作
        '''
        
        # 该时间段 每个动作已经执行的次数
        action_counts = {k: 0 for k in self.action_limits}
        propaganda_results = []
        # 获取领域关键字
        # domain_keywords = await self.get_domain_keywords(domain=domain)
        _,response = await general_generation_think([{"role":"system","content":generate_domain_keywords_prompt(language=self.language)},{"role":"user","content":domain}]) # 32B
        domain_keywords = response.split(',')
        self.log.info(f'生成的 {domain} 关键字是：{domain_keywords}')
        
        # 获取账号人设
        character =  await self.get_account_character(account_id=int(account_id))
        self.log.info(f'账号{account_id}的人设是：{character}')

        try:
            # 用论文的关键字去检索
            if self.posts:
                '''
                根据论文的关键字检索贴文
                - 如果和论文相关，则进行评论/转发，并推荐自己的论文
                - 如果和论文不相关，但是和领域相关，则点赞/评论/快转/转发，转发和评论过程中不推荐自己的论文
                '''   # 小红书的时间转换
                if self.platform == 'twitter':
                    today = convert_time_us(datetime.now().replace(hour=0, minute=0, second=0, microsecond=0))
                elif self.platform == 'xiaohongshu':   
                    # xhs平台选择两天前的帖子
                    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                    today = today - timedelta(days=1)

                for keyword in paper_info['Gene_keywords'] : #+ domain_keywords:
                    keyword = keyword.lower().strip()
                    await asyncio.sleep(random.uniform(5,15))
                    article_element = None
                    while True:   
                        await asyncio.sleep(random.uniform(3,10))
                        post_info, article_element = await bot.get_one_keyword_content(account_id=account_id,keyword=keyword,article=article_element)
                        if not post_info and not article_element:
                            self.log.info(f'未获得有效的贴文内容，继续查找下一个贴文')
                            break # 继续查找下一个关键词
                        if (self.platform == 'twitter' and datetime.strptime(post_info['post_time_ip'], "%Y-%m-%dT%H:%M:%S.%fZ")<today )or (self.platform == 'xiaohongshu' and datetime.strptime(post_info['post_time_ip'],"%Y-%m-%d %H:%M:%S") < today):
                            self.log.info(f'已经获取到前一天的贴文，不进行操作，更换关键词')
                            await bot.close_now_windows()
                            break  
                        # 判断贴文和论文、领域是否相关，相关的话则分配动作；如果不相关，则不分配动作
                        action = await self.handle_action(domain=domain,post_info=post_info,paper_info=paper_info,action_counts=action_counts)
                        if not action:
                            await bot.close_now_windows()
                            continue
                        if action == 'None':
                            return propaganda_results  # 动作达到上限，此时间段不再执行任何动作
                        self.log.info(f'此时间段已经执行过的动作是: {action_counts}， 对当前帖子要执行的动作是：{action}')
                        propaganda_result = await self.dispatch_action(bot=bot,account_id=account_id,character=character,action=action,published=post_info,paper_info=paper_info) # 执行动作
                        propaganda_results.append(propaganda_result)
                        if action == '仅评论'  or action == '仅转发':
                            action = self.action_alias[action]
                        action_counts[action] += 1
                        await bot.close_now_windows() # 关闭当前窗口
                        await asyncio.sleep(random.uniform(3,8))
            # 检查当前
            if action_counts == self.action_limits: return propaganda_results
            if self.persons:
                '''
                根据领域关键字检索账号，根据账号的description判断是否对领域感兴趣，感兴趣的话就判断账号是否活跃(30天内发过帖子)
                如果账号是活跃的，则和该用户进行交互：点赞、评论、转发、快转
                或者可以从大v账号里随机选择账号进行交互
                '''
                # 随机选择 10 个该领域的大v账号进行交互
                v_persons = read_data_from_txt(path =  r'D:\code\ALL_agent\ALL_agent\information\paperagent\recommendation system\object_urls_new.txt')
                v_persons = [{"url":p.split(',')[0],"nickname":p.split(',')[1]} for p in v_persons]
                v_persons = random.sample(v_persons,min(10,len(v_persons)))
                for v_person in v_persons:
                    await asyncio.sleep(random.uniform(3,10))
                    # 爬取每个用户的5个贴文 进行操作
                    response = await bot.scrap_content(account_id=account_id,url=v_person["url"],num=10,time_limit=5)
                    all_posts = json.loads(response.body.decode()).get("response")
                    if isinstance(all_posts,str) or (isinstance(all_posts,list) and len(all_posts) == 0):
                        self.log.info(f'{v_person["nickname"]}近两日的贴文为空/爬取失败')
                        continue
                    # 对每个贴文执行动作
                    for post_info in random.sample(all_posts,min(10,len(all_posts))):
                        action = await self.handle_action(domain=domain,post_info=post_info,paper_info=paper_info,action_counts=action_counts,object_type='person')
                        if not action: continue
                        elif action == 'None': return propaganda_results# 动作达到上限不再继续操作
                        self.log.info(f'此时间段已经执行过的动作是: {action_counts}， 对当前帖子要执行的动作是：{action}')
                        propaganda_result  = await self.dispatch_action(bot=bot,account_id=account_id,character=character,action=action,published=post_info,paper_info=paper_info) # 执行动作
                        propaganda_results.append(propaganda_result)
                        if action == '仅评论'  or action == '仅转发':
                            action = self.action_alias[action]
                        action_counts[action] += 1
                        await asyncio.sleep(random.uniform(5,15))
            # 检查当前
            if action_counts == self.action_limits: return propaganda_results
            
            if self.communities:  
                '''
                根据领域关键字检索社区，根据社区的description判断对domain是否感兴趣。
                若是感兴趣，则爬取活跃社区的帖子，对活跃社区的帖子执行动作
                注: 小红书没有社区
                '''
                # pdb.set_trace()
                scrap = ScrapObjects(log_path=self.log_path)
                # 根据关键字检索社区，并判断是否对domain感兴趣，只返回感兴趣的社区
                all_communities = await scrap.get_target_communities_by_keywords(bot=bot,account_id=account_id,keywords=domain_keywords,domain=domain)
                await asyncio.sleep(random.uniform(5,10))
                # 判断社区是否活跃(5天之内发过帖子),如果活跃则进行交互
                for community_info in all_communities:
                    # 判断账号是否活跃，活跃的话就进行交互，并将账号信息保存下来,5天之内发过帖子就是活跃
                    response_results = await bot.scrap_content(account_id=account_id,url=community_info['community_url'],time_limit=5,num=10)
                    await asyncio.sleep(random.uniform(3,10))
                    latest_tweets = json.loads(response_results.body.decode()).get("response")
                    if isinstance(latest_tweets,str) or (isinstance(latest_tweets,list) and len(latest_tweets) == 0):
                        self.log.info(f"获取 {community_info['community_name']} 社区最近贴文失败/为空")
                        continue 
                    if not self.is_account_active(latest_tweets,num_day=5):   # 5天内如果发过帖子 则表示活跃
                        self.log.info(f"{community_info['community_name']} 社区是不活跃社区，过滤")
                        continue
                    # 是活跃用户，则对贴文进行交互
                    for post_info in latest_tweets:
                        action = await self.handle_action(domain=domain,post_info=post_info,paper_info=paper_info,action_counts=action_counts)
                        if not action: continue
                        elif action == 'None': return propaganda_results
                        self.log.info(f'此时间段已经执行过的动作是: {action_counts}， 对当前帖子要执行的动作是：{action}')
                        propaganda_result = await self.dispatch_action(bot=bot,account_id=account_id,character=character,action=action,published=post_info,paper_info=paper_info) # 执行动作
                        propaganda_results.append(propaganda_result)
                        action = self.action_alias[action] if action == '仅评论'  or action == '仅转发' else action
                        action_counts[action] += 1
                        await asyncio.sleep(random.uniform(3,10))
            
            # 每天再执行一次主动发帖？
            if self.auto_post:
                # 再执行一次主动发帖宣传论文
                await asyncio.sleep(random.uniform(5,10))
                self.log.info(f'账号{account_id}进行主动发帖')
                propaganda_result = await self.dispatch_action(bot=bot,account_id=account_id,character=character,action='发帖',paper_info=paper_info)
                propaganda_results.append(propaganda_result)
            self.log.info(f'账号已经执行完当前时间点的操作')
            return propaganda_results
        except Exception as e:
            self.log.error(f'账号{account_id}检索帖子/账号/社区/发帖时出错：{e}')
            return propaganda_results



    async def handle_action(self,domain:str,post_info:str,paper_info:dict,object_type=None,action_counts:dict=None):
        '''
        判断贴文内容和论文是否相关，如果相关则执行操作：转发/评论，并宣传自己的论文
        如果和论文内容不相关，则判断和领域是否相关
        如果和领域相关，则执行操作：转发/评论/点赞/快转等，不宣传自己的论文
        如果和领域不相关，则不执行操作

        domain 改成：dict？加上domain的描述？
        '''
        if post_info is None or post_info['content'] == '':
            self.log.info(f'贴文内容为空，不执行任何动作')
            return None
        
        # CONTENT = f'''贴文内容：\n {post_info['content']} \n\n  论文摘要：\n {paper_info['Abstract']}'''
        # think, response = await general_generation_think([{"role":"system","content":filter_relevance_paper_prompt()},{"role":"user","content":CONTENT}])
        think, response = await general_generation_think([{"role":"system","content":system_paper_relative_chinese},{"role":"user","content":user_paper_relative_chinese.format(post_text=post_info['content'],paper_abstract=paper_info['Abstract'])}])
        
        self.log.info(f'判断贴文{post_info["note_url"]}和论文是否相关，模型输出内容是：{think}，判断结果是：{response}')
        if response == '是' : # 判断是否和论文相关
            self.log.info(f'该帖文内容和论文相关')
            if self.platform == 'twitter':
                candidates = ['转发','评论','点赞'] if object_type != 'person' else ['转发','评论','关注','点赞']  # '快转',
            if self.platform == 'xiaohongshu':
                candidates = ['收藏','评论','点赞'] if object_type != 'person' else ['收藏','评论','关注','点赞'] 
        else: # 判断是否和领域有关，
            # domain_content = '''推荐系统（Recommendation Systems，简称RS） 是人工智能与数据科学的重要研究方向，旨在通过建模用户与物品的关系，为用户提供个性化的信息筛选与决策支持。其核心任务包括用户建模、物品建模、排序与推荐、冷启动问题、推荐结果解释与评估等。推荐系统广泛应用于电商平台的商品推荐、社交媒体的信息流排序、短视频和音乐平台的内容分发、在线教育中的课程推荐、广告投放优化以及跨模态推荐等场景。'''
            # think,response = await general_generation_think([{"role":"system","content":filter_interest_domain_prompt(domain=domain,content=domain_content)},{"role":"user","content":post_info['content']}])
            think,response = await general_generation_think([{"role":"system","content":system_domain_relative_chinese},{"role":"user","content":user_domain_relative_chinese.format(domain=domain,content=post_info['content'])}])
           
            self.log.info(f'判断贴文{post_info["note_url"]}和领域{domain}是否相关，模型输出内容是：{think}，判断结果是：{response}')
            if response == '是' :
                self.log.info(f'该帖文内容和论文不相关，和领域{domain}相关')
                if self.platform == 'twitter':
                    candidates = ['点赞','仅评论','仅转发']  # '快转',
                if self.platform == 'xiaohongshu':
                    candidates = ['点赞','仅评论','收藏']
            else:
                self.log.info(f'该帖文内容和论文、领域均不相关，不执行任何操作')
                return None

        valid_candidates = []
        for a in candidates:
            acction  = self.action_alias[a] if a == '仅评论' or a == '仅转发' else a
            if action_counts[acction] < self.action_limits[acction]:
                valid_candidates.append(a)
        
        if not valid_candidates:  # 候选动作都超限
            self.log.info("所有候选动作已达上限，该时间段不再执行任何操作，等待下一个时间段")
            return 'None'
        
        random.shuffle(valid_candidates)
        action = random.choice(valid_candidates) # 随机选择一个动作   
        return action   # 返回action


    def is_account_active(self,tweets:list=None, num_day:int=365):
        #判断活跃账户，最新发帖时间是近num_day天的。
        current_date = datetime.now()
        one_year_ago = current_date - timedelta(days=num_day)
        for tweet in tweets:
            latest_time = tweet["post_time_ip"].split('T')[0]
            if latest_time == '' or latest_time == None:
                return False  
            latest_time = datetime.strptime(latest_time,'%Y-%m-%d')
            if one_year_ago <= latest_time <= current_date:
                return True
        return False




    async def dispatch_action(self,bot,account_id,character:str,action:str,paper_info:dict,published:dict=None):
        '''
        根据动作 进行相关操作
        -bot:
        -account_id : 账号
        -character :账号人设
        -action : 要执行的动作
        -published :原帖的信息
        -paper_info : 论文信息
        -model : 模型名称
        '''
        try:
            # 检索 该账号是否对该贴文进行了action操作，如果操作过了就不再继续操作v
            if published:
                sql = f'''SELECT * FROM {self.platform}_interaction WHERE Account_id ={int(account_id)} AND URL = '{published["note_url"]}' AND Action = '{action}';'''
                select_result = self.database.get_dict_data_sql(sql=sql)
                if select_result:
                    self.log.info(f'{self.platform}平台的账号{account_id}已经对该贴文{published["note_url"]}进行了{action}操作，不再进行操作')
                    return 

            if '评论' in action or '转发' in action:
                if action == '仅评论' or action == '仅转发' : # 仅评论贴文内容，不推荐自己的论文
                    # CONTENT  = f'''贴文内容:\n {published["content"]} '''
                    # _,content = await general_generation_think([{"role": "system", "content": only_comment_prompt(character=character,language=self.language)},{"role": "user", "content": CONTENT}])
                    content = await general_generation_deepseek([{"role": "system", "content": system_comment_chinese},
                                                                {"role": "user", "content": user_comment_chinese.format(character=character,post_text=published["content"],language=self.language)}])
   
                if action == '评论' or action == '转发':      # 转发/评论过程中，也要推荐自己的论文
                    # CONTENT = f'''贴文内容:\n {published["content"]} \n\n 论文摘要: \n {paper_info["Abstract"]}'''
                    # _,content = await general_generation_think([{"role": "system", "content": paper_transmit_commment_prompt(character=character,language=self.language)},{"role": "user", "content": CONTENT}])
                    content = await general_generation_deepseek([{"role": "system", "content": system_comment_and_paper_chinese},
                                                                {"role": "user", "content": user_comment_and_paper_chinese.format(character=character,post_text=published["content"],paper_title=paper_info["Title"],paper_abstract=paper_info["Abstract"],language=self.language)}])
                self.log.info(f'模型生成的{action}内容是：{content}')
                # 检查生成的内容是否符合人设，进行反思改写
                think,content = await general_generation_think([{"role": "system", "content": system_reflective_rewrite_chinese},
                                                                {"role": "user", "content": user_reflective_rewrite_chinese.format(platform=self.platform,character=character,post_text=published["content"],draft=content,max_chars=self.max_length,lang=self.language)}])
                print(think)
                self.log.info(f'经过反思改写之后，模型生成的{action}内容是：{content}')

                await asyncio.sleep(random.uniform(3,10))
                content = ''.join(c for c in content if ord(c) <= 0xFFFF) 
                content = self.cut_content(content,max_length=self.max_length-50)  # 截断，预留出论文链接位
                
                if action == '评论' or action == '转发':
                    # 添加论文链接
                    content  = content.replace('Link',paper_info["URL"])   # 替换[Link]
                    pattern = re.compile(r"https?://\s*arxiv\s*\.\s*org/\S*", flags=re.IGNORECASE)   # 匹配论文链接
                    if re.search(pattern, content):
                        content = re.sub(pattern, paper_info["URL"], content)
                    else:
                        links = [
                            f'{paper_info["URL"]}',f'Paper: {paper_info["URL"]}.',f'Preprint: {paper_info["URL"]}.',f'PDF: {paper_info["URL"]}.',f'arXiv: {paper_info["URL"]}.', f'Read more: {paper_info["URL"]}.',f'More details: {paper_info["URL"]}.',f'Full text: {paper_info["URL"]}.',
                            f'Full paper: {paper_info["URL"]}.',f'Find it here: {paper_info["URL"]}.',f'Link: {paper_info["URL"]}.',f'Here it is: {paper_info["URL"]}.',f'For reference: {paper_info["URL"]}.',f'Reference: {paper_info["URL"]}.', f'See also: {paper_info["URL"]}.',f'Further reading: {paper_info["URL"]}.',
                            f'If useful: {paper_info["URL"]}.',f'Method & results: {paper_info["URL"]}.',f'Exp. details: {paper_info["URL"]}.',f'Benchmarks: {paper_info["URL"]}.',f'Context: {paper_info["URL"]}.' f'Citation link: {paper_info["URL"]}.',f'Quick link: {paper_info["URL"]}.',f'Short link: {paper_info["URL"]}.',
                            f'One-click: {paper_info["URL"]}.', f'Worth a look: {paper_info["URL"]}.',f'Have a look: {paper_info["URL"]}.', f'Notes & fig.: {paper_info["URL"]}.',f'Appendix: {paper_info["URL"]}.',f'Project page: {paper_info["URL"]}.',f'Doc: {paper_info["URL"]}.',f'{paper_info["URL"]}'
                        ]

                        content += random.choice(links)
                file_paths = random.choice([paper_info["image_paths"],[]])  # 评论推荐论文的时候 可加图片可不加图片
                if action == '转发':
                    response = await bot.transmits(account_id=int(account_id),url=published["note_url"],content=content,file_paths=file_paths) 
                    content_url  =  json.loads(response.body.decode()).get("response").split('成功：')[-1]
                if action == '仅转发':
                    await bot.transmits(account_id=int(account_id),url=published["note_url"],content=content)   
                    content_url = None
                if action == '评论': 
                    response = await bot.comments(account_id=int(account_id),url=published["note_url"],content=content,file_paths=file_paths) 
                    content_url  =  json.loads(response.body.decode()).get("response").split('成功：')[-1]
                if action == '仅评论':
                    await bot.comments(account_id=int(account_id),url=published["note_url"],content=content) 
                    content_url = None
            elif action == '快转':
                await bot.transmits(account_id=int(account_id),url=published["note_url"],content=None)
                content_url = None
            elif action == '点赞':
                await bot.likes(account_id = int(account_id),url = published["note_url"])
                content_url = None
            elif action == '关注':
                await bot.follows(account_id=int(account_id),url=published["note_url"])
                content_url = None
            elif action == '收藏':
                await bot.collects(account_id=int(account_id),url=published["note_url"])
                content_url = None
            elif action == '发帖':  # 主动发帖宣传论文
                text = f'\n论文标题是: {paper_info["Title"]} \n论文摘要是: {paper_info["Abstract"]}' 
                _,content = await general_generation_think([{"role": "system", "content": post_paper_prompt(character=character,language=self.language,max_length=self.max_length)},{"role": "user", "content": text}])    
                self.log.info(f'模型生成的发帖内容是：{content}')
                content = ''.join(c for c in content if ord(c) <= 0xFFFF) 
                content = self.cut_content(content,max_length=self.max_length)
                content += paper_info["URL"]
                self.log.info(f'经过字数检查之后要发帖的内容是：{content}')
                if self.platform  == 'twitter':
                    response = await bot.posts(account_id=int(account_id),content=content,file_paths=paper_info['image_paths'])
                    content_url  =  json.loads(response.body.decode()).get("response").split('成功：')[-1]
                if self.platform  == 'xiaohongshu':
                    await bot.posts(account_id=int(account_id),content=content,file_paths=paper_info['image_paths'],tags=paper_info['Gene_keywords'])
            # 在该页面进行浏览
            bot.scroll(duration=random.uniform(8,15))
            await asyncio.sleep(random.uniform(10,20))

            return {content_url:action} if content_url else None
        except Exception as e:
            self.log.error(f'账号对{published["note_url"]}进行{action}的时候出错，原因是：{e}')
   

    async def get_account_character(self,account_id):
        '''获取账号account_id的人设'''
        # 获取账号人设
        # pdb.set_trace()
        search_sql = f"SELECT * FROM accounts_info WHERE accounts_info.Account_id = {account_id}"
        s = sql_dataset('twitter')
        character_id = s.get_dict_data_sql(search_sql)[0]['Person_id']
        if character_id: # 获取人设
            character_sql = f"SELECT * FROM person WHERE person.Id = {character_id}"
            character = s.get_dict_data_sql(character_sql)[0]["Description"]
        else:
            character = '专心科研的学者，经常在社交平台发布论文相关的内容'
        return character
    


    async def get_notification_messages(self,account,time_limit,bot=None):
        '''
        查看通知，记录通知，并更新贴文的点赞、评论、浏览等数据
        -time_limit : 上一次获取通知的时间，用来获取通知,type:datetime/str, str支持 days,hours,minutes
        
        '''
        try:
            await asyncio.sleep(random.uniform(3, 5))
            if not bot:
                bot = TwitterBot(log_path=f"./logs/twitter/{account}/notification_log.log")  # 初始化账号bot
            now_time = convert_time_us(datetime.now())
            notify_informations =await bot.get_notifications(account_id=int(account),time_limit=time_limit)
            notify_informations = json.loads(notify_informations.body.decode()).get("response")
            if isinstance(notify_informations, list) and notify_informations:
                random.shuffle(notify_informations)
                self.log.info(f'账号{account}共获取到{len(notify_informations)}条新通知，分别是：{notify_informations}')
                # 回复评论/更新账号数据等，然后时间更新为现在
                
            elif isinstance(notify_informations,list) and not notify_informations:
                self.log.info(f'账号{account}暂时无新通知')
                # 时间更新为现在
                now_time = convert_time_us(datetime.now())
                # bot.driver.quit()
                return now_time # 返回通知时间 datetime类型
            elif isinstance(notify_informations,str):
                self.log.info(f'账号{account}获取通知失败')
                # bot.driver.quit()
                return notify_informations  # 返回错误信息

           
            # 获取账号人设,根据账号人设来回复评论
            character =  await self.get_account_character(account_id=int(account))
            self.log.info(f'账号{account}的人设是：{character}')
    
            # 回复 评论，并更新到数据库中
            for notify_information in notify_informations:
                # 通知类型为：用户点赞/reposted，则更新该条贴文的数据
                if notify_information['notify_type'] == 'liked' or notify_information['notify_type'] == 'reposted':
                    select_sql = f'''SELECT * FROM twitter_records  WHERE URL = "{notify_information['note_url']}" AND Account_id = {int(account)};'''
                    select_result = self.database.get_dict_data_sql(select_sql)
                    if not select_result: # 数据库中暂无该条贴文的记录，则添加
                        insert_sql = '''INSERT INTO twitter_records (`Account_id`,`Platform`,`Type`,`Form`,`URL`,`Content`,`Likes_Num`,`Transmits_Num`,`Views_Num`,`Bookmarks_Num`,`Comments_Num`,`Published_Time_IP`,`Images_URL`,`Update_time`) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s);'''
                        self.database.operation(insert_sql,(int(account),'twitter',notify_information['note_type'],notify_information['note_form'],notify_information['note_url'],notify_information['content'],notify_information['likes'],notify_information['transmits'],
                                                            notify_information['views'],notify_information['bookmarks'],notify_information['comments'],notify_information['post_time_ip'],str(notify_information['images_url']),datetime.now()))
                    else:
                        update_sql = '''UPDATE twitter_records SET Likes_Num = %s,Transmits_Num = %s,Views_Num = %s,Bookmarks_Num = %s,Comments_Num = %s,Update_time = %s WHERE URL = %s And Account_id = %s;'''
                        self.database.operation(update_sql,(notify_information['likes'],notify_information['transmits'],notify_information['views'],notify_information['bookmarks'],notify_information['comments'],datetime.now(),notify_information['note_url'],int(account)))
                    self.log.info(f"已更新twitter内容曝光表中{notify_information['note_url']}的点赞数-评论数-浏览量等信息")
                 
                elif notify_information['notify_type'] == 'replied':
                    # 通知类型为评论，则根据人设生成回复内容并进行回复
                    # 检查交互表中是否已经回复过了，如果回复过了则不再继续回复
                    select_sql = f'''SELECT * FROM twitter_interaction WHERE URL = '{notify_information["note_url"]}' AND Action = "评论" AND Account_id={account};'''
                    select_result = self.database.get_dict_data_sql(sql=select_sql)
                    if select_result:
                        self.log.info(f'账号{account}已经回复过评论{notify_information["note_url"]}，不再重复回复')
                        continue
                    # 回复评论
                    content = await general_generation([{"role":"system","content":reply_comment_prompt(character=character,content=notify_information['original_content'],language='英文')},
                                                        {"role":"user","content":notify_information['content']}])
                    
                    self.log.info(f'模型生成的回复评论内容是：{content}')
                    content = ''.join(c for c in content if ord(c) <= 0xFFFF) 
                    content = self.cut_content(content,max_length=270)
                    self.log.info(f'经过字数检查之后要评论的内容是：{content}')
                    await bot.comments(account_id=int(account),url=notify_information["note_url"],content=content)
                    self.log.info(f'账号{account}回复用户{notify_information["actors_url"]}评论成功！')
                time.sleep(5)
            # bot.driver.quit()  # 关闭浏览器
            return now_time # 返回通知时间 datetime 类型
        except Exception as e:
            self.log.error(f'账号{account}执行get_notification_messages函数获取通知失败, 错误信息：{e}')
            return f'账号{account}执行get_notification_messages函数获取通知失败'


    async def auto_get_notifications_serial(self,account_ids):
        '''
        多个账号，获取通知，并回复

        '''
        time_limit = convert_time_us(datetime.now()- timedelta(days=6)) # 第一次，获取1天前的通知
        accounts_time = { account_id: time_limit for account_id in account_ids}   # 每个账号和它的time_limit
        # 每5小时执行一次
        while True:
            # 获取每一个账号的通知
            for account_id in account_ids:
                accounts_time[account_id] = await self.get_notification_messages(account_id, accounts_time[account_id])  
                if isinstance(accounts_time[account_id],str):
                    # 函数执行失败，结束 
                    self.log.info(f'账号{account_id}获取通知失败，结束')
                    continue 
                elif isinstance(accounts_time[account_id],datetime):
                    self.log.info(f'账号{account_id}获取通知时间成功')
                    continue
                time.sleep(10)
            self.log.info(f'等待5小时，5小时之后继续获取通知')
            await asyncio.sleep(5 * 60 * 60)    


    def cut_content(self,content:str,max_length: int = 230):
        '''如果长度大于max_length，则删除'''
        if len(content) > max_length:
            # 使用正则表达式按 . 或 ! 或换行符 切分句子，并保留分隔符
            parts = re.split(r'([.!?"—;]|\n)', content)
            
            # 将句子和其对应的分隔符重新组合
            sentences = []
            for i in range(0, len(parts), 2):
                sentence = parts[i]
                if i + 1 < len(parts):
                    sentence += parts[i+1]
                sentences.append(sentence)

            longest = ''
            for sentence in sentences:
                sentence = sentence.strip()
                if not sentence:
                    continue

                # 检查添加新句子（带一个空格）后是否会超长
                if not longest:
                    # 第一个句子
                    if len(sentence) <= max_length:
                        longest = sentence
                    else:
                        longest = sentence[:max_length]  # 如果第一个句子太长，直接截断
                        break # 第一个句子就太长了
                else:
                    if len(longest) + 1 + len(sentence) <= max_length:
                        longest += ' ' + sentence
                    else:
                        break
            content = longest 
        return content




if __name__ == "__main__":
    # 这里举例
    agent = PaperAgent(log_path=f'./logs/paperagent/paperagent_llm4rec_log.log')
    asyncio.run(agent.auto_cultivation(account_ids=[1],domain='Large Language Models for Recommendation',paper_path=r'D:\论文agent\2025-08-20'))   # 多个账号串行运营

    
    
'''
可创建数据库存放论文信息，直接从数据库中读取论文信息 ，（但是如果发帖的话就没有图片了🤔）
auto_cultivation函数中 ，可根据 领域，从 数据库中获取论文标题和arxiv链接。
若是已经宣传过的论文，则做个标记。

一个账号可宣传多篇同领域的论文，
一篇论文可被同领域的多个账号宣传。

'''
    
# export PYTHONIOENCODING=utf-8
# nohup python paper_agent/paper_agent.py >> paper_agent/paper_agent_1030.log 2>&1 &

# pid = 5651
        



            

