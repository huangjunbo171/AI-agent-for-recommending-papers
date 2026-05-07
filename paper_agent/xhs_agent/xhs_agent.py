import sys
import os
pythonpath = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0,pythonpath)
from utils.log import logger
from utils.sql import sql_dataset
from xhs_agent.xhs_bot import XiaohongshuBot
from xhs_agent.xhs_planner import XiaohongshuPlanner
from datetime import datetime,timedelta
import json
import random
import time
import pdb
import asyncio
import pandas as pd
from utils.generation import generation_comment,generation_post,general_generation


class XiaohongshuAgent():
    def __init__(self,log_path):
        self.log_path = log_path
        self.log = logger(filename=self.log_path)
        self.database = sql_dataset('xiaohongshu')

    async def get_action_time(self,account_ids,url=None,history=None,current_time=None,is_predict=True):
        accounts = []
        for account_id in account_ids:
            if account_ids.index(account_id) == 0:
                if is_predict:
                    planner = XiaohongshuPlanner(log_path=f"./logs/xhs/{account_id}/xhs_log.log")
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



    async def auto_cultivation(self,account_ids,url=None,model=None,topic_path=None):
        self.log.info(f'''开始培育账号:{account_ids}''')
        #确认每个账号的操作时间没有过期
        while True:
            accounts = []  # [{'account_id':["06:57","09:46"]},{}]
            for account_id in account_ids:
                search_sql = f"SELECT * FROM accounts_info WHERE accounts_info.Account_id = {account_id}"
                result = self.database.get_dict_data_sql(search_sql)[0]
                current_time = datetime.now()
                self.log.info(f'''当前时间为：{current_time}''')
                # 如果result["Prediction_Action_Time"]是空，则重新预测时间
                if result["Prediction_Action_Time"] is None:
                    planner = XiaohongshuPlanner(log_path=f"./logs/xhs/{account_ids[0]}/xhs_log.log")
                    history = await planner.get_history(account_id=account_ids[0],url=url) if url else None
                    self.log.info(f'''获取到的历史信息为：{history}''')
                    accounts = await self.get_action_time(account_ids,url=url,history=history,current_time=current_time)
                else:
                    action_time = json.loads(result["Prediction_Action_Time"])
                    #如果当前时间大于最后一次操作时，重新预测时间
                    if current_time > datetime.strptime(action_time[-1]["date"], "%Y-%m-%d"):
                        planner = XiaohongshuPlanner(log_path=f"./logs/xhs/{account_ids[0]}/xhs_log.log")
                        history = await planner.get_history(url=url) if url else None
                        self.log.info(f'''获取到的历史信息为：{history}''')
                        accounts = await self.get_action_time(account_ids,url=url,history=history,current_time=current_time)
                    else:
                        accounts = await self.get_action_time(account_ids,url=url,current_time=current_time,is_predict=False)

            # pdb.set_trace()
            # 将账号时间规范化
            self.log.info(f'账号的操作时间是：{accounts}')
            planner =XiaohongshuPlanner(log_path=f"./logs/xhs/{account_ids[0]}/xhs_log.log")
            accounts = planner.fomat_action_time(accounts) 
            self.log.info(f"规范化后的账号时间为：{accounts}") 

            while True:
                now_time = datetime.now().strftime("%H:%M")
                # now_time = '12:00'
                current_hour = now_time.split(":")[0]
                account_dict = {time:ids for time,ids in accounts.items() if time.split(":")[0] == current_hour}
                self.log.info(f'''当前时间为：{now_time}，当前小时的操作账号为：{account_dict}''')
                if account_dict:
                # if now_time in accounts.keys():
                    search_sql = f"SELECT * FROM accounts_info WHERE accounts_info.Account_id = {account_ids[0]}"
                    result = self.database.get_dict_data_sql(search_sql)[0]
                    character_id = result['Person_id']
                    if character_id: # 获取人设
                        datebase = sql_dataset('agent')
                        character_sql = f"SELECT * FROM person WHERE person.Id = {character_id}"
                        character = datebase.get_dict_data_sql(character_sql)[0]["Description"]
                    else:
                        character = None
                    planner = XiaohongshuPlanner(log_path=f"./logs/xhs/{account_ids[0]}/xhs_log.log")
                    topics_informations= []
                    if topic_path:
                        # 星云大师 从话题池中获取话题
                        topics_informations = await planner.get_topics_information(topic_path=topic_path)
                    for time_key,ids in account_dict.items():
                        while True:
                            if now_time < time_key:
                                now_time = datetime.now().strftime("%H:%M")
                                self.log.info(f'''当前时间为：{now_time}，未到达操作时间：{time_key}''')
                                time.sleep(30)
                                continue
                            # 星云大师,从话题池中随机选一个话题
                            if topics_informations:
                                for account in ids:
                                    topic_information = random.sample(topics_informations,1) 
                                    self.log.info(f'''对于账户{account}获取到的话题为：{topic_information[0]}''')
                                    content,response_time = await generation_post(text=topic_information[0],model=model,output_len=200,character=character)
                                    content = ''.join(c for c in content if ord(c) <= 0xFFFF)
                                    self.log.info(f'要发布的内容是：{content}')
                                    # 从星云大师的微博获取图像
                                    image_path = await planner.get_xingyun_picture(account=account)
                                    if image_path:
                                        self.log.info(f'要发布的图片路径是：{image_path}')
                                    else:
                                        self.log.info(f'未获得有效的图像路径，此次将不进行发帖')
                                        continue
                                    xhs = XiaohongshuBot(log_path=f"./logs/xhs/{account}/xhs_log.log")  
                                    await xhs.posts(account_id=int(account),content=content,file_paths=image_path,tags=['佛言佛语'],usage='picture')
                                    xhs.driver.quit()
                                    time.sleep(30)
                            break # 下一个时间段
                        break
                else:
                    self.log.info('等待到达目标时间')
                    time.sleep(50)



           