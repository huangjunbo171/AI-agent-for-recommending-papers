# from bot.twitter_bot import TwitterBot
import sys
# sys.path.append("D:\\Desktop\\jmrh")
import os
import sys 
pythonpath = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0,pythonpath)
try:
    from twitter_agent.twitter_bot import TwitterBot
except ModuleNotFoundError:
    from twitter_bot import TwitterBot
from utils.log import logger
from utils.utils import convert_time_us
from collections import defaultdict
from datetime import datetime
from utils.prompt import prediction_action,GENERAL_PLAN,filter_interested_content,filter_interested_content_from_following
from utils.generation import general_generation
import json
import os
from utils.sql import sql_dataset
import pdb
from datetime import timedelta
import random
import time
try:
    from twitter_agent.scrap_news_bot import ScrapNewsBot
except ModuleNotFoundError:
    from scrap_news_bot import ScrapNewsBot


class TwitterPlanner:
    def __init__(self,log_path=f"./logs/planner/planner_log.log"):
        self.log_path = log_path
        self.log = logger(filename=self.log_path)
        self.database = sql_dataset('twitter')
        # self.bot = TwitterBot()

    async def get_topics_information(self,topic_path=None):
        '''获取话题池,用于星云大师'''
        topics_information= []
        with open(topic_path,'r',encoding='utf-8') as f:
            topics_information = json.load(f)
        # self.log.info(f'获取的话题信息是：{topics_information}')
        return topics_information
    

    async def get_target_information(self,account_id,bot):
        '''获取关注列表 的目标人物的帖子，进行点赞/评论'''
        
        # 判断following.txt文件是否存在
        os.makedirs('./information/followings/twitter/',exist_ok=True)
        file_path = f'./information/followings/twitter/{account_id}_following.txt'
        # bot = TwitterBot(log_path=self.log_path)
        # bot.login(account_id=account_id)
        time.sleep(1)
        target_informations = []
        following_results = []
        if os.path.exists(file_path):
            self.log.info(f'账号{account_id}的关注文件存在,可直接读取文件')
            with open(file_path, "r", encoding="utf-8") as file:
                following_results = file.readlines()  
                following_results = [result.strip() for result in following_results]  # 去除每行末尾的换行符
            if not following_results:
                self.log.info(f'账号{account_id}的关注文件中无关注列表，获取其关注列表')
                following_results = bot.get_user_following(account_id=account_id)
        else:
            self.log.info(f'账号{account_id}的关注文件不存在，获取其关注列表')
            following_results = bot.get_user_following(account_id=account_id)
        # 获取目标人物，最近五天发布的帖子
        current_date = datetime.now().strftime("%Y-%m-%d")
        today = datetime.now()
        if len(following_results) == 0:
            self.log.info(f'未获得{account_id}账号的关注列表')
            # bot.driver.driver.quit()
            time.sleep(random.uniform(1,3))
            return target_informations

        sample_size = min(len(following_results), 5)
        for following in random.sample(following_results, sample_size):
            time.sleep(random.uniform(1,3))
            target_information = []
            nickname = following.split('/')[-1]
            # 三天 爬取一次
            for i in range(1,4):
                check_date = (today - timedelta(days=i)).strftime('%Y-%m-%d')
                save_path = f'./information/followings/targets/{nickname}/{check_date}/posts.json'
                if os.path.exists(save_path):
                    self.log.info(f'{following}近三天发布的帖子json文件已经存在，可直接读取文件')
                    with open(save_path, 'r', encoding='utf-8') as file:
                        for line in file:
                            data = json.loads(line.strip())
                            target_information.append(data)
                    self.log.info(f'获取到的{following}帖子信息是：{target_information}')
                    break  # 不再查找下一个日期
            if len(target_information) == 0: # 不存在文件，则到主页爬取
                # 检查是否是目标人物的链接
                with open('./data/target_url.txt', 'r', encoding='utf-8') as file:
                    targets = file.readlines()  
                    targets = [result.strip() for result in targets]  # 去除每行末尾的换行符
                if following in targets:
                    os.makedirs(f'./information/followings/targets/{nickname}/{current_date}',exist_ok=True)
                    save_path = f'./information/followings/targets/{nickname}/{current_date}/posts.json'
                    target_information = await bot.scrap_content(account_id=account_id,url=following,time_limit=3,save_path=save_path)
                    target_information = json.loads(target_information.body.decode()).get("response")
                    if isinstance(target_information,list):
                        target_information = [item for item in target_information if item]  # 过滤掉空字典
                        if len(target_information) != 0:
                            self.log.info(f'获取到的{following}帖子信息是：{target_information}')  # 可能为空
                        else:
                            self.log.info(f'获取到的{following}帖子信息是空的')
                            continue  # 下一个following
                    elif isinstance(target_information,str):
                        self.log.info(f'未获取到{following}有效的帖子信息')
                        continue
                else:
                    continue  # 下一个关注
            # os.makedirs(f'./information/followings/targets/{nickname}/{current_date}',exist_ok=True)
            # save_path = f'./information/followings/targets/{nickname}/{current_date}/posts.json'
            # if os.path.exists(save_path):
            #     target_information = []
            #     self.log.info(f'{following}近七天发布的帖子json文件已经存在，可直接读取文件')
            #     with open(save_path, 'r', encoding='utf-8') as file:
            #         for line in file:
            #             data = json.loads(line.strip())
            #             target_information.append(data)
            #     self.log.info(f'获取到的{following}帖子信息是：{target_information}')
            # else:
            #     # 检查是否是目标人物的链接
            #     with open('./data/target_url.txt', 'r', encoding='utf-8') as file:
            #         targets = file.readlines()  
            #         targets = [result.strip() for result in targets]  # 去除每行末尾的换行符
            #     if following in targets:
            #         target_information = await bot.scrap_content(account_id=account_id,url=following,time_limit=5,save_path=save_path)
            #         target_information = json.loads(target_information.body.decode()).get("response")
            #         if isinstance(target_information,list):
            #             self.log.info(f'获取到的{following}帖子信息是：{target_information}')
            #         elif isinstance(target_information,str):
            #             self.log.info(f'未获取到{following}有效的帖子信息')
            #             continue
            #     else:
            #         continue
            time.sleep(random.uniform(1,3))
            target_informations.extend(target_information)
            if len(target_information) >=5:
                break # 总共获取5个信息即可。。。方便运营
        self.log.info(f'账号{account_id}获取到的目标人物近五天内的帖子信息是：{target_informations}')
        # bot.driver.driver.quit()
        return target_informations


    async def get_interested_information_for_account(self,account_id,all_information=None,characters=None):
        '''根据账号的人设判断账号account_id是否感兴趣的内容'''
        interested_news,interested_followings,interested_information = [],[],[]
        current_date = datetime.now().strftime("%Y-%m-%d")
        try_num = 0

        if characters=='':
            return all_information  # 没有人设描述，则直接返回
        if all_information:    
            for information in all_information:
                filter_prompt = filter_interested_content(character=characters)
                while True:
                    try:
                        response = await general_generation([{"role":"system","content":filter_prompt},{"role":"user","content":information['content']}])
                        self.log.info(f"判断是否感兴趣内容生成结果为：{response}")
                        response = eval(response)
                        if response:
                            information.update(response)
                            # self.log.info(f"获取的感兴趣的信息为：{information}")
                            interested_information.append(information)
                            os.makedirs(f"./information/interests/{account_id}", exist_ok=True)
                            with open(f"./information/interests/{account_id}/{current_date}.json","a",encoding="utf-8") as file:
                                file.write(json.dumps(information, ensure_ascii=False) + "\n")
                            try_num = 0
                            break
                        if response == {}:
                            self.log.info("对信息不感兴趣")
                            break
                    except Exception as e:
                        self.log.error(f"生成格式错误，解析失败: {e}")
                        try_num += 1
                        if try_num > 5:
                            break
        else:
            self.log.info("获取信息来源失败")
            return [],[]
        # 将感兴趣的内容划分成新闻/热搜+关注列表
        for information in interested_information:
            if "news" in information.keys():   
                interested_news.append(information)
            else:
                interested_followings.append(information)
        return interested_news,interested_followings 

    async def get_interested_paper_for_account(self,account_id,all_information=None,prompt=None):
        '''根据账号的人设判断账号account_id是否感兴趣的内容'''
        interested_information = []
        current_date = datetime.now().strftime("%Y-%m-%d")
        try_num = 0
         
        for information in all_information:
            
            while True:
                try:
                    response = await general_generation([{"role":"system","content":prompt},{"role":"user","content":information['content']}])
                    self.log.info(f"判断是否感兴趣内容生成结果为：{response}")
                    response = eval(response)
                    if response:
                        interested_information.append(information)
                        os.makedirs(f"./information/interests/{account_id}", exist_ok=True)
                        with open(f"./information/interests/{account_id}/{current_date}.json","a",encoding="utf-8") as file:
                            file.write(json.dumps(information, ensure_ascii=False) + "\n")
                        try_num = 0
                        break
                    if response == {}:
                        self.log.info("对信息不感兴趣")
                        break
                except Exception as e:
                    self.log.error(f"生成格式错误，解析失败: {e}")
                    try_num += 1
                    if try_num > 5:
                        break
        return interested_information
                

    async def get_all_informations(self,account_id,news=True,followings=True,url=None,following_path=None):
        '''为账号account_id获取新闻信息/关注好友的信息'''
        self.log.info(f"输入的信息为account_id = {account_id},bbc={news},followings={followings},url={url}")
        news_information,following_information,hot_information = [],[],[]

        current_date = datetime.now().strftime("%Y-%m-%d")

        if news: 
            newsbot = ScrapNewsBot(log_path=f'./logs/scrap_news/{account_id}/scrap_news.log')  # 爬取新闻
            
            cnn_information = newsbot.get_topic_content_from_cnn(account_id=account_id,num=10) # cnn news
            self.log.info(f"获取的cnn新闻为：{cnn_information}")
            newsbot.driver.quit()
            time.sleep(2)
            news_information.extend(cnn_information)
        if followings:
            twitter = TwitterBot(log_path=self.log_path)
            #如果url不为空，获取关注列表最新消息,否则获取热搜
            if url is None:
                
                # 获取热搜词
                result = await twitter.get_hot_words(account_id=account_id) # 里边会登录
                hotwords_list = json.loads(result.body.decode()).get("response")
                if isinstance(hotwords_list,str):
                    self.log.info(f'未获取到有效的热搜词')
                elif isinstance(hotwords_list,list):
                    for hot_word in hotwords_list:
                        # hot_content = await twitter.get_keyword_contents(account_id=account_id,keyword=hot_word)
                        hot_content = await twitter.scrap_content(account_id=account_id,keyword=hot_word)
                        hot_content = json.loads(hot_content.body.decode()).get("response")
                        if isinstance(hot_content,list):
                            self.log.info(f'热搜词{hot_word}获取到的内容是：{hot_content}')
                            hot_information.extend(hot_content)
                        elif isinstance(hot_content,str):
                            self.log.info(f'热搜词{hot_word}未获取到有效的内容')
                self.log.info(f"获取的热搜内容为：{hot_information}")
            else:
                # 如果没有给路径，则选择url的关注列表,并写入文件
                user_name = url.split('/')[-1]
                following_path = f"./information/followings/{user_name}/following.txt"
                if os.path.exists(following_path):
                    self.log.info(f'{user_name}关注列表的文件已经存在，可直接读取文件')
                    with open(following_path, 'r', encoding='utf-8') as file:
                        urls = file.readlines()  
                        following_list  = [result.strip() for result in urls]  # 去除每行末尾的换行符
                else:
                    await twitter.login_by_cookies(account_id=account_id) # 仅使用 cookies 登录
                    following_list = twitter.get_user_following(url=url)  # 获取harris的关注列表
                following_list = list(set(following_list))  # 去重
                if len(following_list) >= 5:
                    following_list = random.sample(following_list, 5)
                os.makedirs(f"./information/followings/{user_name}/", exist_ok=True)
                save_path=f"./information/followings/{user_name}/{current_date}.json"
                for following_url in following_list:
                    following_content = await twitter.scrap_content(account_id=account_id,url=following_url,time_limit=5,save_path=save_path)
                    following_content = json.loads(following_content.body.decode()).get("response")
                    if isinstance(following_content,list):
                        self.log.info(f'获取到的{following_url}最新一天的帖子信息是：{following_content}')
                    elif isinstance(following_content ,str):
                        self.log.info(f'未获取到有效的{following_url}最新一天帖子信息')
                        continue
                    following_information.extend(following_content)
            twitter.driver.quit()
            time.sleep(2)

        # 返回获取到的所有信息
        all_information = news_information + following_information + hot_information
        return all_information

    async def get_interested_information(self,account_id,news=True,followings=True,url=None,characters=None,following_path=None):
        """从bbc、cnn、热搜、关注列表获取感兴趣的信息"""
        self.log.info(f"输入的信息为account_id = {account_id},bbc={news},followings={followings},url={url},characters={characters}")
        bbc_information,cnn_information,following_information,hot_information,interested_information = [],[],[],[],[]

        current_date = datetime.now().strftime("%Y-%m-%d")
        try_num = 0
        
        if news: 
            newsbot = ScrapNewsBot(log_path=f'./logs/scrap_news/{account_id}/scrap_news.log')  # 爬取新闻
            # bbc_information = bot.get_topic_content_from_bbc(account_id=account_id) # bbc news,只获取1页的bbc新闻
            # self.log.info(f"获取的bbc新闻为：{bbc_information}")
            cnn_information = newsbot.get_topic_content_from_cnn(account_id=account_id,num=15) # cnn news
            self.log.info(f"获取的cnn新闻为：{cnn_information}")
            newsbot.driver.quit()
            time.sleep(2)
        if followings:
            twitter = TwitterBot(log_path=self.log_path)
            #如果url不为空，获取关注列表最新消息,否则获取热搜
            if url is None:
                
                # 获取热搜词
                result = await twitter.get_hot_words(account_id=account_id) # 里边会登录
                hotwords_list = json.loads(result.body.decode()).get("response")
                if isinstance(hotwords_list,str):
                    self.log.info(f'未获取到有效的热搜词')
                elif isinstance(hotwords_list,list):
                    for hot_word in hotwords_list:
                        # hot_content = await twitter.get_keyword_contents(account_id=account_id,keyword=hot_word)
                        hot_content = await twitter.scrap_content(account_id=account_id,keyword=hot_word)
                        hot_content = json.loads(hot_content.body.decode()).get("response")
                        if isinstance(hot_content,list):
                            self.log.info(f'热搜词{hot_word}获取到的内容是：{hot_content}')
                            hot_information.extend(hot_content)
                        elif isinstance(hot_content,str):
                            self.log.info(f'热搜词{hot_word}未获取到有效的内容')
                self.log.info(f"获取的热搜内容为：{hot_information}")
            else:
                # 如果没有给路径，则选择url的关注列表,并写入文件
                user_name = url.split('/')[-1]
                following_path = f"./information/followings/{user_name}/following.txt"
                if os.path.exists(following_path):
                    self.log.info(f'{user_name}关注列表的文件已经存在，可直接读取文件')
                    with open(following_path, 'r', encoding='utf-8') as file:
                        urls = file.readlines()  
                        following_list  = [result.strip() for result in urls]  # 去除每行末尾的换行符
                else:
                    await twitter.login_by_cookies(account_id=account_id) # 仅使用 cookies 登录
                    following_list = twitter.get_user_following(url=url)  # 获取harris的关注列表
                following_list = list(set(following_list))  # 去重
                if len(following_list) >= 5:
                    following_list = random.sample(following_list, 5)
                os.makedirs(f"./information/followings/{user_name}/", exist_ok=True)
                save_path=f"./information/followings/{user_name}/{current_date}.json"
                for following_url in following_list:
                    following_content = await twitter.scrap_content(account_id=account_id,url=following_url,time_limit=5,save_path=save_path)
                    following_content = json.loads(following_content.body.decode()).get("response")
                    if isinstance(following_content,list):
                        self.log.info(f'获取到的{following_url}最新一天的帖子信息是：{following_content}')
                    elif isinstance(following_content ,str):
                        self.log.info(f'未获取到有效的{following_url}最新一天帖子信息')
                        continue
                    following_information.extend(following_content)
            twitter.driver.quit()
            time.sleep(2)
        all_information = bbc_information + cnn_information + following_information + hot_information

        if characters=='':
            return all_information  # 没有人设描述，则直接返回

        if all_information:    
            for information in all_information:
                filter_prompt = filter_interested_content(character=characters)
                while True:
                    try:
                        response = await general_generation([{"role":"system","content":filter_prompt},{"role":"user","content":information['content']}])
                        self.log.info(f"判断是否感兴趣内容生成结果为：{response}")
                        response = eval(response)
                        if response:  
                            information.update(response)
                            # self.log.info(f"获取的感兴趣的信息为：{information}")
                            interested_information.append(information)
                            os.makedirs(f"./information/interests/{account_id}", exist_ok=True)
                            with open(f"./information/interests/{account_id}/{current_date}.json","a",encoding="utf-8") as file:
                                file.write(json.dumps(information, ensure_ascii=False) + "\n")
                            try_num = 0
                            break
                        if response == {}:
                            self.log.info("对信息不感兴趣")
                            break
                    except Exception as e:
                        self.log.error(f"生成格式错误，解析失败: {e}")
                        try_num += 1
                        if try_num > 5:
                            break
        else:
            self.log.info("获取信息来源失败")
        
        # 将感兴趣的内容划分成新闻/热搜+关注列表
        news_information = []
        other_information = []
        for information in interested_information:
            if "news" in information.keys():   
                news_information.append(information)
            else:
                other_information.append(information)
        return news_information,other_information         



    def fomat_action_time(self, action_times):
        #将{"id":[time]}转换为{"time":[id]}
        # 创建一个空字典用于存储时间为key，id为value的结构
        # 创建一个空字典用于存储 time: [id]
        time_to_ids = {}

        # 遍历列表中的每个字典
        for entry in action_times:
            for id_, times in entry.items():
                for time in times:
                    if time not in time_to_ids:
                        time_to_ids[time] = []  # 初始化一个空列表
                    time_to_ids[time].append(id_)  # 将id添加到对应时间的列表中

        # 按时间顺序排序字典
        sorted_time_dict = dict(sorted(time_to_ids.items()))
        return sorted_time_dict


    def format_time(self,results):
        #将用户近期的行为序列进行规范化
        time_sequence = {}
        for result in results:
            if result["post_time_ip"] == '':
                continue
            post_time = datetime.strptime(result["post_time_ip"], '%Y-%m-%dT%H:%M:%S.%fZ')   
            date_str = post_time.strftime("%Y-%m-%d")
            time_str = post_time.strftime("%H:%M")
            weekday_str = post_time.strftime("%A")
            if date_str not in time_sequence:
                time_sequence[date_str] = {"weekday": weekday_str, "detail": []}
            time_sequence[date_str]["detail"].append(time_str)
        # pdb.set_trace()
        final_result = []
        for date, info in time_sequence.items():
            info["detail"].sort()
            final_result.append({
                "date": date,
                "weekday": info["weekday"],
                "detail": info["detail"]
            })
        return final_result
    
    async def get_history(self,account_id,url:str):
        """
        获取人物历史的行为数据
        """
        self.log.info(f"开始获取人物历史的行为数据")
        driver = TwitterBot()
        results = await driver.scrap_content(account_id=account_id,url=url,time_limit=30)
        driver.driver.quit()
        results = json.loads(results.body.decode()).get("response")
        if isinstance(results,list):
            self.log.info(f"获取到的人物历史的行为数据为：{results}")
            return results
        elif isinstance(results,str):
            self.log.error(f'获取人物历史的行为数据失败')
            return []
        

    async def get_prediction_time(self,url:str=None,account_id:int=None,history=None):
        """
        预测账户操作时间
        如果是仿人物
        1.获取人物历史的行为数据
        2.提取时间序列并排序
        3.预测账号未来一周的活跃时间
        如果是普通账户：直接预测
        """
        self.log.info(f"输入的信息为url={url},account_id={account_id},history={history}，开始预测账户{account_id}操作时间")
        # self.log.info(f"开始预测账户{account_id}操作时间")
        if url is not None and history:
            formatted_time = self.format_time(history)
            self.log.info(f"提取到的时间序列：{formatted_time}")
            today = convert_time_us(datetime.now())#.strftime("%Y-%m-%d %H:%M:%S")
            self.log.info(f"当前时间：{today}")
            # 获取未来一周的时间序列
            outputs = []
            for i in range(7):
                predict_time = (today + timedelta(days=i)).strftime("%Y-%m-%d")
                imitation_prompt = prediction_action(f'{predict_time}')
                response = await general_generation([{"role":"system","content":imitation_prompt},{"role":"user","content":f'''{formatted_time}'''}])
                self.log.info(f"预测的{predict_time}的活跃时间为：{response}")
                response = eval(response)
                # action_time = {response["date"]:response["detail"]}
                outputs.append(response)
        else:
            outputs = []
            today = convert_time_us(datetime.now())#.strftime("%Y-%m-%d %H:%M:%S")
            self.log.info(f"当前时间：{today}")
            for i in range(7):
                predict_time = (today + timedelta(days=i)).strftime("%Y-%m-%d")
                imitation_prompt = prediction_action(f'{predict_time}')
                response = await general_generation([{"role":"system","content":GENERAL_PLAN},{"role":"user","content":f'''{predict_time}'''}])
                self.log.info(f"预测的{predict_time}的活跃时间为：{response}")
                response = eval(response)
                # 对response进行后处理，如果detail大于1，则随机选择一个时间，确保一天只活跃一个时间段
                details = response["detail"]
                if len(details) > 1:
                    response["detail"] = random.sample(details,1)
                # action_time = {response["date"]:response["detail"]}
                outputs.append(response)
        self.log.info(f"预测的未来一周的活跃时间为：{outputs}")
        sql = '''UPDATE accounts_info SET Prediction_Action_Time = %s WHERE Account_id = %s'''
        self.database.operation(sql,(json.dumps(outputs),account_id,))

        return outputs
    
   

    # async def get_prediction_time(self,url:str,account_id:int):
    #     """
    #     预测账户操作时间
    #     如果是仿人物
    #     1.获取人物历史的行为数据
    #     2.提取时间序列并排序
    #     3.预测账号未来一周的活跃时间
    #     如果是普通账户：直接预测
    #     """
    #     if url is not None:
    #         self.log.info(f"开始获取人物历史的行为数据")
    #         self.bot.login(account_id=account_id)
    #         results = await self.bot.get_all_content(url=url,time_limit=30)  # 获取harris过去30天的历史操作记录
    #         self.log.info(f"获取人物历史的行为数据成功：{results}")


    #         formatted_time = self.format_time(results)
    #         self.log.info(f"提取到的时间序列：{formatted_time}")
    #         today = convert_time_us(datetime.now())#.strftime("%Y-%m-%d %H:%M:%S")
    #         self.log.info(f"当前时间：{today}")
    #         # 获取未来一周的时间序列
    #         outputs = []
    #         for i in range(7):
    #             predict_time = (today + timedelta(days=i)).strftime("%Y-%m-%d")
    #             imitation_prompt = prediction_action(f'{predict_time}')
    #             response = await general_generation([{"role":"system","content":imitation_prompt},{"role":"user","content":f'''{formatted_time}'''}])
    #             self.log.info(f"预测的{predict_time}的活跃时间为：{response}")
    #             response = eval(response)
    #             # action_time = {response["date"]:response["detail"]}
    #             outputs.append(response)
    #     else:
    #         outputs = []
    #         for i in range(7):
    #             predict_time = (today + timedelta(days=i)).strftime("%Y-%m-%d")
    #             imitation_prompt = prediction_action(f'{predict_time}')
    #             response = await general_generation([{"role":"system","content":GENERAL_PLAN},{"role":"user","content":f'''{predict_time}'''}])
    #             self.log.info(f"预测的{predict_time}的活跃时间为：{response}")
    #             response = eval(response)
    #             # action_time = {response["date"]:response["detail"]}
    #             outputs.append(response)
    #         # response = general_generation([{"role":"system","content":GENERAL_PLAN}])
    #         # self.log.info(f"一般规划结果为：{response}")
    #         # outputs = eval(response)

    #     self.log.info(f"预测的未来一周的活跃时间为：{outputs}")
    #     sql = "UPDATE account_tw SET Prediction_action_time = %s WHERE Id = %s"
    #     self.database.operation(sql,(json.dumps(outputs),account_id,))

    #     return outputs
    
    # async def action_plan(self):
    #     """
    #     一般规划
    #     """
    #     response = general_generation([{"role":"system","content":GENERAL_PLAN}])
    #     self.log.info(f"一般规划结果为：{response}")
    #     response = eval(response)
    #     return response


# import asyncio
# # # str1.encode('utf-8').decode('unicode_escape')
# # async def main():
# #     planner = Planner()
# #     await planner.get_prediction_time(url="https://x.com/KamalaHarris",account_id=1)
# # asyncio.run(main())
# if __name__ == '__main__':
#     planner = TwitterPlanner()
#     # asyncio.run(planner.get_interested_information(url='https://weibo.com/u/1749127163'))
#     asyncio.run(planner.get_prediction_time(url="https://x.com/KamalaHarris",account_id=11))

