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
from utils.generation import *

import pdb

from paper_agent.paper_agent import PaperAgent
from twitter_agent.twitter_bot import TwitterBot
from xhs_agent.xhs_bot import XiaohongshuBot

# 并行
# async def main():
#     accounts = [224,1]  # 多个账号
#     handler = PaperAgent(log_path='./logs/paperagent/notifications/notifications.log')

#     # '''多个账号并行执行'''
#     # tasks = [handler.auto_get_notifications(account_id) for account_id in accounts]
#     # await asyncio.gather(*tasks)

#     '''多个账号串行执行'''
#     await handler.auto_get_notifications_serial(account_ids=accounts)

# if __name__ == "__main__":
#     asyncio.run(main())


# nohup python paper_agent/run_notifications.py >> paper_agent/notifications_1015.log 2>&1 &
#  nohup python paper_agent/debot.py >> paper_agent/ndebot1022.log 2>&1 &
















import ast
import time
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo
TZ = ZoneInfo("Asia/Shanghai")

# 构造platform和bot的映射
platform_to_bot = {
    "twitter": TwitterBot,
    "xiaohongshu": XiaohongshuBot
}
numeric_fields_by_platform = {
    'twitter':     ['Likes','Transmits','Views','Bookmarks','Comments'],
    'xiaohongshu': ['Likes','Collects','Comments'],
}

class StaticPosts():
    def __init__(self,platform:str='twitter',log_path='./logs/static/twitter/static_log.log'):
        self.platform = platform
        self.log_path = log_path    
        self.log = logger(filename=self.log_path)
        self.database = sql_dataset(self.platform)


        
    def next_run_time(self,now: datetime | None = None) -> datetime:
        now = now or datetime.now()
        days_until_sun = (6 - now.weekday()) % 7
        candidate_date = (now + timedelta(days=days_until_sun)).date()
        target = datetime.combine(candidate_date, dtime(23, 55))
        if now > target:
            target += timedelta(days=7)
        return target


    async def job_async(self,account_ids:list,platform:str,target_time:datetime):
        for account_id in account_ids:
            pdb.set_trace()
            all_results,sum_results = await self.static_of_posts(account_id=account_id,platform=platform,target_time=target_time)
            if len(all_results) == 0 and not sum_results:
                self.log.info(f'平台{platform}账号{account_id}本周没有发布贴文/评论')
                continue
            self.log.info(f'平台{platform}账号{account_id}本周帖子的数据量分别是：{all_results}')
            self.log.info(f'平台{platform}账号{account_id}本周帖子的总数据量是：{sum_results}')
            await asyncio.sleep(random.uniform(2,5))
            



    async def static_of_posts(self,account_id:int,platform:str,target_time:datetime):
        '''
        查询数据库，查询这一周发布的帖子链接等 ，然后统计帖子的数据量
        
        统计帖子的数据量：浏览量、点赞量、评论量、转发量等，并更新到数据库中
        '''
        pdb.set_trace()
        # 查询贴文的链接
        start_time = target_time - timedelta(days=7)
        select_sql = f'''SELECT * FROM {platform}_interaction WHERE Interaction_time >= '{start_time}' AND Interaction_time <= '{target_time}' AND Account_id = {int(account_id)} AND (Action = '转发' or Action = '评论' or Action = '发帖');'''
        select_results = self.database.get_dict_data_sql(select_sql)
        if not select_results:
            self.log.info(f'平台{platform}的账号{account_id}本周没有发布新帖子/评论等')
            return [],None
        self.log.info(f'平台{platform}账号{account_id}本周发布了{len(select_results)}条新帖子/评论等')

        bot = platform_to_bot[platform](log_path=self.log_path)
        self.log.info(f'登录平台 {platform} 账号 {account_id}')
        # await bot.login_by_cookies(account_id = int(account_id))  # 登录账号
        await bot.login_by_cookies(account_id = 8)   #  登录账号8统计该周的一个数据量
        all_results= []

        for select_result in select_results:
            await asyncio.sleep(random.uniform(random.uniform(3,8),random.uniform(10,20)))
            action_type = select_result['Action']
            # 获取贴文的链接
            try:
                (note_url,note_content), = ast.literal_eval(select_result['Result_list'])[0].items()
            except:
                s = select_result['Result_list'].strip().strip('"')
                m = re.match(r'^(https?://\S+?)(?=:(?!/))', s)  # 直到冒号，且冒号后不是 '/'
                note_url = m.group(1) if m else None
            if not note_url:
                self.log.info('Result_list 无法解析出有效 URL，已跳过')
                continue

            data = await bot.get_one_content(url=note_url)   
            if not data:
                self.log.info(f'{note_url}已经被删除/不存在内容')
                continue
            
            self.log.info(f'贴文{note_url}的数据是：{data}')

            # 更新数据库,先查询曝光表中是否存在这条记录，若存在则更新，不存在则添加
            records_sql = f'''SELECT * FROM {platform}_records  WHERE URL = "{note_url}" AND Account_id = {int(account_id)};'''
            records_result = self.database.get_dict_data_sql(records_sql)
            if platform == 'twitter': # 类型更改为action类型？
                if not records_result:  
                    insert_sql = '''INSERT INTO twitter_records (`Account_id`,`Platform`,`Type`,`Form`,`URL`,`Content`,`Likes_Num`,`Transmits_Num`,`Views_Num`,`Bookmarks_Num`,`Comments_Num`,`Published_Time_IP`,`Images_URL`,`Update_time`) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s);'''
                    self.database.operation(insert_sql,(int(account_id),'twitter',action_type,data['note_form'],data['note_url'],data['content'],data['likes'],data['transmits'],
                                                        data['views'],data['bookmarks'],data['comments'],data['post_time_ip'],str(data['images_url']),datetime.now()))
                else:
                    update_sql = '''UPDATE twitter_records SET Likes_Num = %s,Transmits_Num = %s,Views_Num = %s,Bookmarks_Num = %s,Comments_Num = %s,Update_time = %s WHERE URL = %s And Account_id = %s;'''
                    self.database.operation(update_sql,(data['likes'],data['transmits'],data['views'],data['bookmarks'],data['comments'],datetime.now(),data['note_url'],int(account_id)))
                result = {"note_url":note_url,"Likes":int(data['likes']),"Transmits":int(data['transmits']),"Views":int(data['views']),"Bookmarks":int(data['bookmarks']),"Comments":int(data['comments'])}
                all_results.append(result)

            if platform == 'xiaohongshu': # 类型更改为action类型？
                if not records_result:
                    insert_sql = '''INSERT INTO `xiaohongshu_records`(`Account_id`,`Platform`,`URL`,`Source_nickname`,`Source_redid`,`Title`,`Content`,`Likes_Num`,`Collects_Num`,`Comments_Num`,`Published_Time_IP`,`Type`,`Form`,`Images_URL`,`Update_time`) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s);'''
                    self.database.operation(insert_sql,(account_id,'xiaohongshu',data['note_url'],data["nickname"],data["redid"],data["title"],data["content"],data["likes"],
                                                        data["collects"],data["comments"],data["post_time_ip"],data["note_type"],data["note_form"],str(data["images_url"]),datetime.now()))
                else:
                    update_sql = '''UPDATE xiaohongshu_records SET Likes_Num = %s,Collects_Num = %s,Comments_Num = %s,Update_time = %s WHERE URL = %s And Account_id = %s;'''
                    self.database.operation(update_sql,(data['likes'],data['collects'],data['comments'],datetime.now(),data['note_url'],int(account_id)))
                result = {"note_url":note_url,"Likes":int(data['likes']),"Collects":int(data['collects']),"Comments":int(data['comments'])}
                all_results.append(result)
            self.log.info(f'已更新贴文{note_url}的数据')
            bot.scroll(random.uniform(random.uniform(3,8),random.uniform(10,20)))
        if not all_results:
            return [], {}  # 如果为空，则返回空
        
        bot.driver.quit()
        await asyncio.sleep(random.uniform(15,25))
        numeric_fields = numeric_fields_by_platform.get(self.platform, [])
        sum_results = {
            k: sum(int(r.get(k, 0) or 0) for r in all_results if k in r)
            for k in numeric_fields
        }

        # keys = list(all_results[0].keys()) if len(all_results) >  0 else []
        # sum_results = {k: sum(int(r.get(k, 0) or 0) for r in all_results)for k in keys}
        return all_results,sum_results   # 返回本周的数据量
      

    async def scheduler(self,account_ids:list,platform: str = "twitter"):
        '''
        每周日晚23:59点统计该周发帖的情况
        account_ids:list,账号list
        platform:str 平台，默认是twitter
        '''
        while True:
            pdb.set_trace()
            target = self.next_run_time()   # 每周日23:59
            now = datetime.now(TZ)

            now = datetime(2025, 11, 2, 23, 59) 
            target =  datetime(2025, 11, 2, 23, 59) 

            remain = (target - now).total_seconds()
            self.log.info(f"下一次运行时间：{target.isoformat()}，倒计时 {remain:.0f}s")
            await asyncio.sleep(max(0, remain))
            try:
                await self.job_async(account_ids,platform,target)
            except Exception as e:
                self.log.error(f"[{datetime.now(TZ)}] 任务异常: {e!r}")
        

if __name__ == "__main__":
    a  = StaticPosts()
    asyncio.run(a.scheduler(account_ids=[224,1],platform= "twitter"))