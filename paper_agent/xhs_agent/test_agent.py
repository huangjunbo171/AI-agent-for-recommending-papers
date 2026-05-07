import os
import sys 
pythonpath = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0,pythonpath)
from utils.log import logger
from utils.sql import sql_dataset
from .xhs_bot import XiaohongshuBot
from datetime import datetime,timedelta
import json
import random
import time
import pdb
import asyncio
from concurrent.futures import ThreadPoolExecutor
# from utils.utils import convert_time_us,convert_to_traditional
from utils.generation import *
from utils.prompt import *

# from .xiaohongshu_planner import xiaohongshuPlanner

def fomat_action_time(self, action_times):
    #将{"id":[time]}转换为{"time":[id]}
    # 创建一个空字典用于存储时间为key，id为value的结构
    # 创建一个空字典用于存储 time: [id]
    time_to_ids = {}

    # 遍历列表中的每个字典
    for entry in action_times:
        for id_, times in entry.items():
            for time in times:
                time = time.split(':')
                if time not in time_to_ids:
                    time_to_ids[time] = []  # 初始化一个空列表
                time_to_ids[time].append(id_)  # 将id添加到对应时间的列表中

    # 按时间顺序排序字典
    sorted_time_dict = dict(sorted(time_to_ids.items()))
    return sorted_time_dict

class XiaohongshuAgent():
    def __init__(self,log_path:str = "./logs/xiaohongshu/xiaohongshu_log.log"):
        self.log = logger(filename=log_path)
        self.database = sql_dataset('xiaohongshu')
        # self.planner = xiaohongshuPlanner()

                    
                 
    async def auto_cultivation_single(self,account_id,keywords=None,model=None):
        self.log.info(f'''开始培育账号:{account_id}''')
        #确认每个账号的操作时间没有过期
        
        while True:
            #检查所有的操作时间，如果时间为空或失效，重新预测时间
            search_sql = f"SELECT * FROM accounts_info WHERE accounts_info.Account_id = {account_id}"
            result = self.database.get_dict_data_sql(search_sql)[0]
            self.log.info(f'''获取到的账号信息为：{result}''')
            character = ''
            character_id = result['Person_id']
            # interest_list = []
            # pdb.set_trace()
            if character_id: # 获取人设
                
                character_sql = f"SELECT * FROM person WHERE person.Id = {character_id}"
                style = self.database.get_dict_data_sql(character_sql)[0]
                character = style["Description"]
                field = eval(style["Field"])
                # interest_list = eval(style['Interest'])
            current_time = datetime.now()
            self.log.info(f'''当前时间为：{current_time}''')
            
            if result["Prediction_Action_Time"] is None:
                action_times = await self.predict_action_time(account_id)
            else:
                action_times = json.loads(result["Prediction_Action_Time"])
                
            if current_time > datetime.strptime(action_times[-1]["date"], "%Y-%m-%d"):
                action_times = await self.predict_action_time(account_id)
            date_time =current_time.strftime("%Y-%m-%d")
            for item in action_times:
                if item["date"] == date_time:  
                    action_time = item['detail']  
                    break          

            self.log.info(f'''账号{current_time}的操作时间为：{action_time}''')
            
            action_hour = [item.split(':')[0] for item in action_time]
            self.log.info(f'''规范化后的账号时间为：{action_hour}''')#{"time":[id]}时间以小时计算
            # pdb.set_trace()
            is_action = False
            while True:
                now_time = datetime.now()
                if now_time.strftime("%Y-%m-%d") != current_time.strftime("%Y-%m-%d"):
                    break
                current_hour = now_time.strftime("%H:%M").split(":")[0]
                # current_hour = '12'
                # 提取所有属于当前小时的时间点
                if current_hour not in action_hour:
                    self.log.info(f'''当前时间为：{now_time}，当前小时的操作时间为：{action_hour}，未到达操作时间''')
                    is_action = False
                    time.sleep(random.uniform(600,1740))
                    continue
                if is_action:
                    self.log.info(f"当前小时已经发布过内容，等待下一个操作时间")
                    time.sleep(random.uniform(600,1740))
                #提取所有的关键词的信息
                is_action = False
                all_information = [] 
                # pdb.set_trace()
                keywords_list = []
                if field:
                    self.log.info(f'''对于账号{account_id}，感兴趣的领域是：{field}''')
                    keyword_sql = f"SELECT Id, Keywords FROM news WHERE Field = '{field[0]}' AND Keywords IS NOT NULL AND Keywords != '' ORDER BY Update_time DESC LIMIT 20"
                    keywords = self.database.get_dict_data_sql(keyword_sql)
                    keywords = random.sample(keywords, 2)
                    self.log.info(f'''对于账号{account_id}，获取到的关键词是：{keywords}''')
                    if not keywords:
                        self.log.info(f"对于账号{account_id}，没有获取到关键词")
                        continue
                    for item in keywords:
                        keyword = item['Keywords']
                        if not keyword:
                            continue
                        keyword = keyword.split(' ')
                        keywords_list.extend(keyword)
                if keywords_list:
                    keywords_list = list(set(keywords_list))
                    bot = XiaohongshuBot(log_path=f"./logs/xiaohongshu/{account_id}/xiaohongshu_log.log")   # 初始化一个bot
                    # await bot.login_by_password(account_id=int(account_id))
                    await bot.login_by_cookies(account_id=int(account_id))
                    for keyword in keywords_list:
                        
                        informations = await bot.scrap_content(account_id=account_id,num=10,url='')
                        informations = json.loads(informations.body.decode()).get("response") 
                        if isinstance(informations,list):
                            all_information.extend(informations)
                        else:
                            self.log.info(f"账号{account_id}没有获取到关键词{keyword}的信息")
                    # bot.driver.quit()
                    
                
                    # time.sleep(300)
                if not all_information:
                    self.log.info('没有爬取到相关信息')
                    continue
            
                self.log.info(f'''对于账户{account_id}获取到的信息是：{all_information}''') 
                #获取感兴趣的帖文信息

                interested_information = await self.get_interested_information(account_id=account_id,all_information=all_information,prompt=filter_interested_character_content(character,field[0]))
                self.log.info(f'''对于账户{account_id}感兴趣的信息是：{interested_information}''')
                               
                random.shuffle(interested_information)
                action_list = [random.choice(['发帖','点赞','评论']) for _ in range(int(random.uniform(10,15)))]
                length = min(len(action_list),len(interested_information))
                bot = XiaohongshuBot(log_path=f"./logs/xiaohongshu/{account_id}/xiaohongshu_log.log") 
                for i in range(length):
                    try:
                        # 发布新闻
                        action = action_list[i]
                        # action = "评论"
                        published = interested_information[i]
                        sql = f'''SELECT * FROM xiaohongshu_interaction WHERE Account_id ={int(account_id)} AND URL = '{published["note_url"]}' AND Action = '{action}';'''
                        select_result = self.database.get_dict_data_sql(sql)
                        if select_result:
                            continue
                        text = published["content"]
                        if action == "发帖":
                              
                            content,response_time = await generation_post(text=text,model=model,output_len=1000,language='中文简体',character=character,style='informal')
                            
                            self.log.info(f'模型生成的发布内容是：{content}')
                            
                            await bot.posts(account_id=int(account_id),content=content)
                            
                        elif action == '点赞':
                            await bot.likes(account_id=int(account_id),url = published["note_url"])

                        elif action == '评论':
                            
                            content,response_time = await generation_comment(text=text,model=model,output_len=200,language='中文简体',style='informal')
                              
                            self.log.info(f'模型生成的评论内容是：{content}')
                            await bot.comments(account_id=int(account_id),url=published["note_url"],content=content)
                            
                        
                        bot.driver.scroll()
                    
                    except:
                        self.log.info(f"执行账号{account_id}出错")
                bot.driver.quit()
                is_action = True

    async def predict_action_time(self,account_id):
        self.log.info(f"输入的信息为account_id={account_id},开始预测账户{account_id}操作时间")
        action_time = []
        today = datetime.now()#.strftime("%Y-%m-%d %H:%M:%S")
        self.log.info(f"当前时间：{today}")
        for i in range(7):
            predict_time = (today + timedelta(days=i)).strftime("%Y-%m-%d")
            response = await general_generation([{"role":"system","content":GENERAL_PLAN},{"role":"user","content":f'''{predict_time}'''}])
            self.log.info(f"预测的{predict_time}的活跃时间为：{response}")
            response = eval(response)
            
            action_time.append(response)
        self.log.info(f"预测的未来一周的活跃时间为：{action_time}")
        sql = '''UPDATE accounts_info SET Prediction_Action_Time = %s WHERE Account_id = %s'''
        self.database.operation(sql,(json.dumps(action_time),account_id,))

        self.log.info(f'''预测到{account_id}的操作时间为：{action_time}''')
        return action_time
    

    async def get_interested_information(self,account_id,all_information=None,prompt=None):
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
                        os.makedirs(f"./information/xiaohongshu/interests/{account_id}", exist_ok=True)
                        with open(f"./information/xiaohongshu/interests/{account_id}/{current_date}.json","a",encoding="utf-8") as file:
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

    async def auto_follow(self,account_ids,file_path):
        '''关注目标人物'''
        results = self.read_results_from_file(file_path=file_path)
        for account_id in account_ids:
            random_results = self.select_random_results(results=results)
            self.log.info(f'账号{account_id}要关注的目标账号是：{random_results}')
            self.log.info(f'登录账号{account_id}')
            bot = XiaohongshuBot(log_path=f"./logs/xiaohongshu/{account_id}/target_log.log")  
            bot.login(account_id=int(account_id)) # 登录一次，后边不需要再登录
            for result in random_results:
                await bot.follows(account_id=account_id,url=result)
                self.log.info(f'账号{account_id}成功关注目标账号：{result}')
                time.sleep(2)
            bot.driver.driver.quit()
        self.log.info(f'所有活跃账号成功关注20-30个目标人物')
    
def run_agent(account_id, model):
    agent = XiaohongshuAgent(log_path=f"./logs/xiaohongshu/{account_id}/xiaohongshu_log.log")
    asyncio.run(agent.auto_cultivation_single(account_id, model=model))   

def auto_cultivation_parallel(account_ids, model=None):
    """
    输入多个 account_id，开多个进程并行执行 auto_cultivation_simple
    """
    import multiprocessing
    import asyncio

    processes = []
    for account_id in account_ids:
        p = multiprocessing.Process(target=run_agent, args=(account_id, model))
        p.start()
        processes.append(p)
    for p in processes:
        p.join()

if __name__ == "__main__":
    # 这里举例
    auto_cultivation_parallel([123, 456], model="your_model")
    
    
    
            

        



            

            

