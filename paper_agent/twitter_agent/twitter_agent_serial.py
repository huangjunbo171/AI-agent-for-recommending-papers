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
from utils.utils import convert_time_us
from utils.generation import generation_post,generation_comment

class TwitterAgent():
    def __init__(self,log_path: str = "./logs/twitter/twitter_log.log"):
        self.log = logger(filename=log_path)
        self.database = sql_dataset('twitter')

    async def get_action_time(self,account_ids,url=None,history=None,current_time=None,is_predict=True):
        accounts = []
        for account_id in account_ids:
            if account_ids.index(account_id) == 0:
                if is_predict:
                    planner = TwitterPlanner(log_path=f"./logs/twitter/{account_id}/twitter_log.log")
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

    
    async def auto_cultivation(self,account_ids,news=True,followings=True,url=None,model=None,topic_path=None):
        self.log.info(f'''开始培育账号:{account_ids}''')
        xingyun_flag = False
        #确认每个账号的操作时间没有过期
        while True:
            
            #利用一个账号获取检查所有的操作时间，如果时间为空或失效，重新预测时间
            search_sql = f"SELECT * FROM accounts_info WHERE accounts_info.Account_id = {account_ids[0]}"
            result = self.database.get_dict_data_sql(search_sql)[0]
            self.log.info(f'''获取到的账号信息为：{result}''')
            
            current_time = convert_time_us(datetime.now())
            self.log.info(f'''当前时间为：{current_time}''')
            
            if result["Prediction_Action_Time"] is None:
                planner = TwitterPlanner(log_path=f"./logs/twitter/{account_ids[0]}/twitter_log.log")
                history = await planner.get_history(account_id=account_ids[0],url=url) if url else None
                self.log.info(f'''获取到的历史信息为：{history}''')
                accounts = await self.get_action_time(account_ids,url=url,history=history,current_time=current_time)
                                   
            else:
                action_time = json.loads(result["Prediction_Action_Time"])
                #如果当前时间大于最后一次操作时，重新预测时间
                if current_time > datetime.strptime(action_time[-1]["date"], "%Y-%m-%d"):
                    planner = TwitterPlanner(log_path=f"./logs/twitter/{account_ids[0]}/twitter_log.log")
                    history = await planner.get_history(account_id=account_ids[0],url=url) if url else None
                    self.log.info(f'''获取到的历史信息为：{history}''')
                    accounts = await self.get_action_time(account_ids,url=url,history=history,current_time=current_time)
                else:
                    accounts = await self.get_action_time(account_ids,url=url,current_time=current_time,is_predict=False)
                    
            self.log.info(f'''账号的操作时间为：{accounts}''')
            planner = TwitterPlanner(log_path=f"./logs/twitter/{account_ids[0]}/twitter_log.log")
            accounts = planner.fomat_action_time(accounts)
            self.log.info(f'''规范化后的账号时间为：{accounts}''')#{"time":[id]}时间以小时计算
            # pdb.set_trace()
            while True:
                now_time = convert_time_us(datetime.now()).strftime("%H:%M")
                # now_time = '14:33'
                current_hour = now_time.split(":")[0]
                # 提取所有属于当前小时的时间点
                account_dict = {time:ids for time,ids in accounts.items() if time.split(":")[0] == current_hour}
                self.log.info(f'''当前时间为：{now_time}，当前小时的操作账号为：{account_dict}''')
                if account_dict:
                    # search_sql = f"SELECT * FROM accounts_info WHERE accounts_info.Account_id = {account_ids[0]}"
                    # result = self.database.get_dict_data_sql(search_sql)[0]
                    # character_id = result['Person_id']
                    # if character_id: # 获取人设
                    #     datebase = sql_dataset('agent')
                    #     character_sql = f"SELECT * FROM person WHERE person.Id = {character_id}"
                    #     character = datebase.get_dict_data_sql(character_sql)[0]["Description"]
                    # else:
                    #     character = None
                    planner = TwitterPlanner(log_path=f"./logs/twitter/{account_ids[0]}/twitter_log.log")
                    topics_informations,news_information,other_information = [],[],[]
                    if topic_path:
                        # 星云大师账号，从话题池中获取话题
                        topics_informations = await planner.get_topics_information(topic_path=topic_path)
                        # self.log.info(f'对于账户{account_dict}获取到的佛学话题为：{topics_informations}')
                    else:
                        # news_information, other_information = await planner.get_interested_information(account_id=int(account_ids[0]),news=news,followings=followings,url=url,characters=character)
                        # self.log.info(f'''对于账户{account_dict}获取到的感兴趣的新闻内容为：{news_information}''')
                        # self.log.info(f'''对于账户{account_dict}获取到的感兴趣的其他内容为：{other_information}''')
                        all_inforamtion = await planner.get_all_informations(account_id=int(account_ids[0]),news=news,followings=followings,url=url)
                        self.log.info(f'''对于账户{account_dict}获取到的信息是：{all_inforamtion}''')
                    
                    for time_key,ids in account_dict.items():
                        while True:
                            if now_time < time_key:
                                now_time = convert_time_us(datetime.now()).strftime("%H:%M")
                                self.log.info(f'''当前时间为：{now_time}，未到达操作时间：{time_key}''')
                                time.sleep(30)
                                continue

                            if topics_informations:
                                for account in ids:
                                    # 星云大师发帖
                                    character = None
                                    topic_information = random.sample(topics_informations,1)  # 随机选一个话题
                                    self.log.info(f'''对于账户{account}获取到的话题为：{topic_information[0]}''')
                                    content,response_time = await generation_post(text=topic_information[0],model=model,output_len=1000,character=character,language='中文繁体')
                                    content =  self.cut_content(content)
                                    self.log.info(f'要发布的内容是：{content}')
                                    bot = TwitterBot(log_path=f"./logs/twitter/{account}/twitter_log.log")  
                                    await bot.posts(account_id=int(account),content=content)
                                    bot.scroll(duration=random.uniform(20,40))
                                    bot.driver.quit()
                                    time.sleep(random.uniform(60,300))
                                time.sleep(1000)
                                xingyun_flag = True
                                break # 星云大师发完贴以后，结束掉循环

                            
                            for account in ids:
                                time.sleep(random.uniform(60,120))
                                # 获取账号account的人设
                                search_sql = f"SELECT * FROM accounts_info WHERE accounts_info.Account_id = {account}"
                                result = self.database.get_dict_data_sql(search_sql)[0]
                                character_id = result['Person_id']
                                if character_id: # 获取人设
                                    datebase = sql_dataset('agent')
                                    character_sql = f"SELECT * FROM person WHERE person.Id = {character_id}"
                                    character = datebase.get_dict_data_sql(character_sql)[0]["Description"]
                                else:
                                    character = None

                                # 根据账号人设判断该账号感兴趣的新闻/帖子
                                if all_inforamtion is None:
                                    self.log.info(f'未获取到任何有效信息，无法根据账号{account}的人设进行筛选')
                                    news_information, formation = [],[] # 定义两个空的列表
                                else:
                                    # 判断账号account感兴趣的内容
                                    self.log.info(f'根据账号{account}的人设：{character} 进行信息筛选')
                                    news_information, other_information = await planner.get_interested_information_for_account(account_id=int(account),all_information=all_inforamtion,characters=character)
                                    self.log.info(f'''对于账户{account}获取到的感兴趣的新闻内容为：{news_information}''')
                                    self.log.info(f'''对于账户{account}获取到的感兴趣的其他内容为：{other_information}''')

                                bot = TwitterBot(log_path=f"./logs/twitter/{account}/twitter_log.log")   # 初始化一个bot
                                self.log.info(f'开始登录账号{account}')
                                await bot.login(account_id=int(account))
                                time.sleep(random.uniform(30,60))
                                # 更新账号的user profile
                                await bot.get_user_profile(account_id=int(account))
                                bot.scroll(duration=random.uniform(10,20))
                                self.log.info(f'获取账号{account}关注的目标人物的五天之内的帖子')
                                try:
                                    target_informations = await planner.get_target_information(account_id=int(account),bot=bot)
                                    self.log.info(f'''对于账户{account}获取到的目标人物近五天的帖子信息是：{target_informations}''') 
                                    bot.scroll(duration=random.uniform(10,18))
                                except Exception as e:
                                    self.log.error(f'获取账号{account}关注的目标人物的帖子失败，错误信息：{e}')
                                    target_informations = []
                                # 定义两个标志位，用来判断是否发帖成功/转发成功
                                news_published = False
                                other_published = False

                                if len(news_information) != 0:
                                    # 发布新闻
                                    for published in news_information:
                                        action = "发帖"
                                        text = published["news"]  # 新闻话题
                                        # 发一个帖子
                                        content,response_time = await generation_post(text=text,model=model,output_len=1000,character=character,language='英文',style='informal')
                                        self.log.info(f'模型生成的发布内容是：{content}')
                                        # self.log.info(f'模型响应时间是：{response_time:.2f} 秒')
                                        content =  self.cut_content(content).replace('#','  ')
                                        self.log.info(f'经过字数检查之后要发布的内容是：{content}')
                                        if content == '':
                                            self.log.info(f'要发布的内容为空，选择下一个新闻内容进行发布')
                                            news_published = False
                                            continue
                                        await bot.posts(account_id=int(account),content=content)
                                        news_published = True # 表示发布成功
                                        break
                                bot.scroll(duration=random.uniform(10,18))
                                if len(other_information) != 0:
                                    # 转发/快转感兴趣的信息
                                    for published in other_information:
                                        #待发布内容的信息来源于url账号的关注列表
                                        action = random.choice(["转发","快转"])
                                        text = published["content"]  # 帖子内容
                                        # 检查数据库中是否已经存在
                                        sql = f'''SELECT * FROM twitter_interaction WHERE Account_id ={int(account)} AND URL = '{published["note_url"]}' AND Action = '{action}';'''
                                        select_result = self.database.get_dict_data_sql(sql)
                                        if select_result:
                                            continue
                                        if action == '转发':
                                            content,response_time = await generation_comment(text=text,model=model,output_len=200,character=character,language='英文',style='informal')
                                            self.log.info(f'模型生成的转发内容是：{content}')
                                            # self.log.info(f'模型响应时间是：{response_time:.2f} 秒')
                                            content =  self.cut_content(content).replace('#','  ')
                                            self.log.info(f'经过字数检查之后要转发的内容是：{content}')
                                            if content == '':
                                                self.log.info(f'要转发的内容为空，选择下一个新闻内容进行发布')
                                                other_published = False 
                                        elif action == '快转':
                                            content = None
                                        await bot.transmits(account_id=int(account),url=published["note_url"],content=content)
                                        other_published = True  # 表示操作成功
                                        break
                                # time.sleep(10)
                                bot.scroll(duration=random.uniform(10,20))  # 在页面随机滑动几秒

                                # 定义标志位，表示 是否评论/点赞成功
                                comment_published = False
                                like_published = False
                                published_break  = False
                                if (len(other_information) == 0 and len(news_information) == 0) or (not news_published and not other_published):  # 如果前边没有转发/发帖的话，则转发目标人物的一条帖子
                                    actions = ["点赞","评论","转发"]
                                    transmit_published = False    # 转发的标志位
                                else:  # 如果前边转发/发帖成功，则不再转发目标人物的帖子
                                    actions = ["点赞","评论"]
                                    transmit_published = True
                                if not target_informations:
                                    
                                    self.log.info(f'账号{account}没有关注任何目标人物，无法进行点赞/评论/转发操作')
                                    continue
                                for published in target_informations:
                                    # 重新定义 actions，点赞/评论/转发 不同的帖子
                                    actions = [action for flag, action in zip([like_published, comment_published, transmit_published],["点赞", "评论", "转发"]) if not flag]
                                    self.log.info(f'账号{account}要对目标人物的帖子进行的操作是：{actions}')
                                    if actions == []:
                                        self.log.info(f'账号{account}已经对目标人物的帖子进行过所有操作')
                                        break
                                    if 'content' not in published:
                                        continue
                                    text = published["content"]  # 帖子内容
                                    if published["note_url"] == 'Unknown':
                                        continue
                                    for action in actions:
                                        # 检查数据库中是否已经存在该操作
                                        sql = f'''SELECT * FROM twitter_interaction WHERE Account_id ={int(account)} AND URL = '{published["note_url"]}' AND Action = '{action}';'''
                                        select_result = self.database.get_dict_data_sql(sql)
                                        if select_result:
                                            self.log.info(f'账号{account}已经对该帖子{published["note_url"]}进行过{action}操作')
                                            published_break = True
                                            break 
                                        if action == '点赞':
                                            await bot.likes(account_id=int(account),url = published["note_url"])
                                            like_published = True # 表示点赞成功
                                            published_break = True
                                            break 
                                        elif action == '评论':
                                            content,response_time = await generation_comment(text=text,model=model,output_len=200,character=character,language='英文',style='informal')
                                            self.log.info(f'模型生成的评论内容是：{content}')
                                            content =  self.cut_content(content).replace('#','  ')
                                            self.log.info(f'经过字数检查之后要评论的内容是：{content}')
                                            if content == '':
                                                self.log.info(f'要评论的内容为空，选择下一个新闻内容进行发布')
                                                comment_published = False
                                                published_break = True
                                                break
                                            await bot.comments(account_id=int(account),url=published["note_url"],content=content)
                                            comment_published = True # 表示评论成功
                                            published_break = True
                                            break 
                                        elif action == '转发':
                                            content,response_time = await generation_comment(text=text,model=model,output_len=200,character=character,language='英文',style='informal')
                                            self.log.info(f'模型生成的转发内容是：{content}')
                                            content =  self.cut_content(content).replace('#','  ')
                                            self.log.info(f'经过字数检查之后要转发的内容是：{content}')
                                            if content == '':
                                                self.log.info(f'要转发的内容为空，选择下一个新闻内容进行发布')
                                                transmit_published = False
                                                published_break = True
                                                break
                                            await bot.transmits(account_id=int(account),url=published["note_url"],content=content)
                                            transmit_published = True # 表示转发成功
                                            published_break = True
                                            break
                                    time.sleep(random.uniform(10,18))
                                    if published_break:
                                        continue  # 找下一个记录
                                    # break
                                bot.scroll(duration=random.uniform(7,20))
                                bot.driver.driver.quit()   
                                
                            break
                        if xingyun_flag:
                            break # 结束掉当前时间点，等待下一个时间点
                    break

                else:
                    self.log.info(f'''当前时间为：{now_time}，未到达操作时间''')
                    time.sleep(300)  
            self.log.info(f'结束循环，关闭运营')
            break
 
    
    
    def cut_content(self,content:str):
        '''如果长度大于280，则删除'''
        if len(content) >275:
            sentences = content.split('.')
            longest = ''
            for sentence in sentences:
                sentence = sentence.strip()  
                # 判断当前累积的句子和新句子的总长度是否小于270
                if len(longest) + len(sentence) + 1 <= 270:  # +1是为了加上句号
                    if longest:  
                        longest += sentence +'.' 
                    else:  
                        longest = sentence
                else:
                    break  # 如果添加新句子超过270
            content = longest
        return content
    


    def read_results_from_file(self,file_path):
        with open(file_path, "r", encoding="utf-8") as file:
            results = file.readlines()  
            results = [result.strip() for result in results]  # 去除每行末尾的换行符
        return results



    def select_random_results(self,results, min_count=20, max_count=30):
        # 随机选择 20 到 30 个名字
        count = random.randint(min_count, max_count)
        selected_results = random.sample(results, count)  # 从列表中随机选择不重复的元素
        return selected_results    
    
    
    async def auto_follow(self,account_ids,file_path):
        '''关注目标人物'''
        results = self.read_results_from_file(file_path=file_path)
        for account_id in account_ids:
            random_results = self.select_random_results(results=results)
            self.log.info(f'账号{account_id}要关注的目标账号是：{random_results}')
            self.log.info(f'登录账号{account_id}')
            bot = TwitterBot(log_path=f"./logs/twitter/{account_id}/target_log.log")  
            await bot.login(account_id=int(account_id)) # 登录一次，后边不需要再登录
            for result in random_results:
                await bot.follows(account_id=account_id,url=result)
                self.log.info(f'账号{account_id}成功关注目标账号：{result}')
                time.sleep(random.uniform(2,5))
            bot.modify_passwd(account_id=account_id)
            bot.driver.driver.quit()
            time.sleep(random.uniform(300,600))
        self.log.info(f'所有活跃账号成功关注20-30个目标人物')
    
    
    
    
    
    
            

        
if __name__ == '__main__':
    agent = TwitterAgent()
    asyncio.run(agent.auto_cultivation(account_ids=[139],news=False,followings=False,model='Xingyun',topic_path='./data/xingyundashi_topic.json'))


            

            

