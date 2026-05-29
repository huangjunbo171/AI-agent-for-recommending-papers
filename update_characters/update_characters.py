import os
import sys
pythonpath = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0,pythonpath)
import json
import time
from utils.log import logger
from utils.sql import sql_dataset
from twitter_agent.twitter_bot import TwitterBot
from facebook_agent.facebook_bot import FacebookBot
from weibo_agent.weibo_bot import WeiboBot
from xhs_agent.xhs_bot import XiaohongshuBot
from kuaishou_agent.kuaishou_bot import KuaishouBot
from dy_agent.douyin_bot import DouyinBot
from toutiao_agent.toutiao_bot import ToutiaoBot
from bilibili_agent.bilibili_bot import BilibiliBot
from extract_portrait import AccountPortrait
import asyncio
import schedule
import pdb
import re
import datetime
from utils.prompt import person_description_prompt
from utils.generation import general_generation

# 构造platform和bot的映射
platform_to_bot = {
    "twitter": TwitterBot,
    "facebook": FacebookBot,
    "xiaohongshu": XiaohongshuBot,
    "weibo":WeiboBot,
    "kuaishou": KuaishouBot,
    "douyin": DouyinBot,
    "toutiao": ToutiaoBot,
    "bilibili": BilibiliBot

}

# 构造platform和数据库的映射
platform_to_db = {
    "twitter": "twitter",
    "facebook": "facebook",
    "xiaohongshu": "xiaohongshu",
    "weibo": "weibo",
    "kuaishou": "kuaishou",
    "douyin": "douyin",
    "toutiao": "toutiao",
    "bilibili": "bilibili"
}


LOG_PATH = './logs/update_character/update_character_log.log'
log = logger(LOG_PATH)


class UpdateCharacter():
    def __init__(self,platform:str,account_id,log_path:str = "./logs/update_character/update_character_log.log"):
        self.log = logger(filename=log_path)
        self.database_name = platform_to_db[platform]
        self.database = sql_dataset(self.database_name)
        self.account_id = account_id
        self.platform = platform
        print(f'平台是{self.platform}, 账号是：{self.account_id}')
   

    async def get_interaction_records(self):
        '''获取一周的交互记录（包括所有的操作）'''
        # pdb.set_trace()
        select_sql = f'''SELECT Content,URL,Action FROM {platform_to_db[self.platform]}_interaction WHERE Account_id = {self.account_id} AND Update_time >= NOW() - INTERVAL 1 WEEK;'''
        # 初始化bot
        bot  = platform_to_bot[self.platform]()
        response_results = await  bot.get_account_interaction(account_id=self.account_id,sql=select_sql)
        bot.driver.quit()  # 关闭bot
        await asyncio.sleep(2)
        response_results = json.loads(response_results.body.decode()).get("response")
        if isinstance(response_results,list):
            # interaction_records = [{"content":item["Content"],"url":item["URL"],"action":item["Action"]} for item in response_results if (item["Content"]!='' and item["Content"]!=None)]   # 交互记录
            # 如果是点赞/快转等操作，则将原贴的内容作为content
            interaction_records = []
            for item in response_results:
                one_record = {}
                if item["Action"] in  ["点赞","快转"]:
                    # 到record表中搜帖子信息
                    select_record = f'''SELECT * FROM {self.database_name}_records WHERE URL = '{item["URL"]}';'''
                    record_result = self.database.get_dict_data_sql(select_record)
                    one_record["content"] =  record_result[0]["Content"] if record_result else ''
                elif item["Action"] in ["滑动","关注","取消关注"]:  # 如果是滑动的动作，则先跳过
                    continue
                else:
                    one_record["content"] = item["Content"]
                one_record["action"] = item["Action"]
                one_record["url"] = item["URL"]
                if one_record["content"] != '':
                    interaction_records.append(one_record)
            
            if len(interaction_records) != 0:
                return interaction_records
            else:
                self.log.info(f'{self.platform}账号{self.account_id}暂无历史交互信息')
                return []
        elif isinstance(response_results,str):
            self.log.info(f'获取账号{self.account_id}历史交互内容失败')
            return []

    async def update_person_history(self,character_id):
        '''
        更新person表中的 character_id的 History 字段
        - character_id：人设id
        '''
        # pdb.set_trace()
        select_sql = f'''SELECT * FROM person WHERE Id = {character_id}'''
        result = self.database.get_dict_data_sql(select_sql)
        self.log.info(f'{character_id}的当前信息是：{result}')
        # 将当前信息加上update_time，添加到history字段中
        # history字段
        history = [] if not result[0]["History"] else eval(result[0]["History"])
        history_dict = result[0]
        history_dict["Update_time"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")  # 更新的时间
        history.append(history_dict)
        # 更新 history  字段
        update_sql = '''UPDATE person SET History = %s WHERE Id = %s'''
        self.database.operation(update_sql,(str(history),character_id))
        self.log.info(f'person 表中 {character_id} 的 History 字段已更新为 {history}')


    async def update_person_description(self,character_id):
        '''
        构造人设，根据person表更新后的兴趣或领域字段，更新person表中的description字段
        - character_id：人设id
        '''

        # pdb.set_trace()
        select_sql = f'''SELECT * FROM person WHERE Id = {character_id}'''
        result = self.database.get_dict_data_sql(select_sql)
        exclude_keys = {"Id", "History"} # 要排除的字段
        # 根据键值对，组成str字符串
        description_parts = []
        for key, value in result[0].items():
            if key not in exclude_keys:
                if value is None or str(value).strip() == "":
                    value = "None"
                description_parts.append(f"{key.lower()}={value}")

        # 合并成一句话
        person_info = ", ".join(description_parts)
        try_num =  0
        while try_num < 5:
            # 调用模型来生成 description
            response_result = await general_generation([{"role":"system","content":person_description_prompt()},{"role":"user","content": person_info}])  # 生成人设描述
            if "角色描述：" in response_result:
                description = response_result.replace("角色描述：","")
                description = re.split("\n",description)[0]
                self.log.info(f"生成描述：{description}")
                # 更新到数据库的description字段，
                update_sql = '''UPDATE person SET Description = %s WHERE Id = %s'''
                self.database.operation(update_sql,(description ,character_id))
                self.log.info(f'person 表中 {character_id} 的 Description 字段已成功更新为 {description }')
                break
            else:
                self.log.info(f"生成人设描述失败：再次生成")
                try_num += 1
                continue
        if try_num == 5:
            self.log.error(f'生成人设描述失败，更新人设描述失败')


    async def update_person_info(self,key:str,value:list):
        '''
        更新person表中的interest、field、history、description字段
        - key: str, 可选 interest、field 表示更新兴趣或领域字段
        - value: list，兴趣、领域字段要更新的值
        '''
        # pdb.set_trace()
        # 获取账号的person_id
        sql = f'''SELECT Person_id FROM accounts_info WHERE account_id = {self.account_id}'''
        character_id = self.database.get_dict_data_sql(sql)[0]["Person_id"]
        self.log.info(f'{self.platform} 账号 {self.account_id} 对应的person_id是 {character_id}')

        # 将当前信息添加到 history 字段中
        await self.update_person_history(character_id = character_id)
        self.log.info(f'person 表中 History 字段已成功更新')
        #  更新兴趣/领域，然后更新description
        if key == 'interest':
            update_sql = '''UPDATE person SET Interest = %s WHERE Id = %s'''
        elif key == 'field':
            update_sql = '''UPDATE person SET Field = %s WHERE Id = %s'''
        self.database.operation(update_sql,(str(value),character_id))
        self.log.info(f'person 表中 {character_id} 的 {key} 字段已成功更新为：{value}')
        # 更新 person 表中的description 字段
        await self.update_person_description(character_id = character_id)
        self.log.info(f'person 表中 Description 字段已成功更新')
       




    async def extract_and_update_interest(self):
        '''
        更新 platform 平台 account_id 的兴趣
        获取一周的交互记录（包括所有的操作），提取每个帖子的兴趣 更新到交互表中
        根据一周的交互记录，更新person表中interest、description和history字段，更新账号属性表中的兴趣和历史兴趣字段

        '''
        # pdb.set_trace()
        # 获取过去一周的社交记录
        interaction_records = await self.get_interaction_records()
        if not interaction_records:
            return f'{self.platform} 账号 {self.account_id} 没有过去一周的历史交互记录'
        
        self.log.info(f'{self.platform} 账号 {self.account_id} 的历史交互信息是：{interaction_records}')  
        # 提取兴趣
        e = AccountPortrait(data = interaction_records,platform=self.platform,account_id=self.account_id)
        await e.generate_key(key = 'interest')  
        self.log.info(f'已更新 交互表 中每条互动记录的兴趣')
        await e.extract_interest() # 抽取一周的主要兴趣
        self.log.info(f'根据一周的交互记录，得到的主要兴趣是：{e.top_interests}')
        # 更新账号account_id兴趣和历史兴趣到social_attributes表中
        bot  = platform_to_bot[self.platform]()
        await bot.update_account_interest(account_id=self.account_id,interest=e.top_interests)
        self.log.info(f'已成功更新 social_attributes 表中账号 {self.account_id} 的兴趣和历史兴趣')
        bot.driver.quit()  # 关闭bot
        await asyncio.sleep(2)
        # 更新person表中的 interest 字段、description字段和history字段
        await self.update_person_info(key='interest', value=e.top_interests)
        self.log.info(f'{self.platform} 账号 {self.account_id}的 person表中 interest、description和history字段已更新')



    async def extract_and_update_field(self):
        '''
        更新 platform 平台 account_id 的领域
        获取一周的交互记录（包括所有的操作），提取每个帖子的领域 更新到交互表中
        根据一周的交互记录，更新person表中field、description和history字段

        '''
        # pdb.set_trace()
        interaction_records = await self.get_interaction_records()
        if not interaction_records:
            return
        self.log.info(f'{self.platform}账号{self.account_id}的历史交互信息是：{interaction_records}')  
        # 根据一周的交互记录 提取领域
        e = AccountPortrait(data = interaction_records,platform=self.platform,account_id=self.account_id)
        await e.generate_key(key = 'field')  
        self.log.info(f'已更新 交互表 中每条互动记录的领域')
        await e.extract_field() # 抽取一周的主要领域
        self.log.info(f'根据一周的交互记录，得到的主要领域是：{e.top_fields}')
        # 更新person表中的  领域字段和历史字段
        await self.update_person_info(key='field', value=e.top_fields)
        self.log.info(f'{self.platform} 账号 {self.account_id}的 person表中 field、description和history字段已更新')



    async def extract_and_update_view(self):
        '''
        更新交互表中 每一条帖子 的观点和立场
        获取一周的交互记录（包括所有的操作），提取每个帖子的观点和立场，并更新到交互表中

        '''
        # pdb.set_trace()
        interaction_records = await self.get_interaction_records()
        if not interaction_records:
            return
        self.log.info(f'{self.platform}账号{self.account_id}的历史交互信息是：{interaction_records}')  
        # 提取观点和立场
        e = AccountPortrait(data = interaction_records, platform=self.platform,account_id=self.account_id)
        await e.generate_key(key = 'view')  
        self.log.info(f'已更新 交互表 中每条互动记录的观点立场')
    
    
    

    # async def update_character(self,platform:str,account_id):
    #     '''
    #     读取交互表，获取一周的交互记录，只获取转发、评论和发帖动作
    #     根据交互内容，对每一条帖子提取观点和立场，并更新到交互表中。
    #     对一周的帖子内容提取主要的兴趣和领域，更新到person表中，并更新 social_attributes 表中兴趣和历史兴趣字段
    #     参数：
    #         -- platform: 平台名称，要做一个映射，根据platform去映射到数据库名/
    #         -- account_id: 账号id
     
    #     '''
    #     # 选择近一周，转发、评论、发帖的内容
    #     select_sql = f'''SELECT Content,URL,Action FROM {platform_to_db[platform]}_interaction WHERE Account_id = {account_id} AND (Action = '评论' OR Action = '发帖' OR Action = '转发') AND Update_time >= NOW() - INTERVAL 1 WEEK;'''
    #     # 初始化bot

    #     bot  = platform_to_bot[platform]()
    #     response_results = await  bot.get_account_interaction(account_id=account_id,sql=select_sql)
    #     # pdb.set_trace()
    #     response_results = json.loads(response_results.body.decode()).get("response")
    #     if isinstance(response_results,list):
    #         # interaction_records = [item["Content"] for item in response_results if item]  # 过滤掉空字典，只保留 评论/发贴/转发的文本内容
    #         interaction_records = [{"content":item["Content"],"url":item["URL"],"action":item["Action"]} for item in response_results if (item["Content"]!='' and item["Content"]!=None)]   # 交互记录
    #         if len(interaction_records) != 0:
    #             self.log.info(f'{platform}账号{account_id}的历史交互信息是：{interaction_records}')  
    #         else:
    #             self.log.info(f'{platform}账号{account_id}暂无历史交互信息')
    #             bot.driver.quit()  # 关闭bot
    #             await asyncio.sleep(2)
    #             return
    #     elif isinstance(response_results,str):
    #         self.log.info(f'获取账号{account_id}历史交互内容失败')
    #         bot.driver.quit()  # 关闭bot
    #         await asyncio.sleep(2)
    #         return
    #     self.log.info(f'根据交互记录，提取观点立场、兴趣和领域, 并将 观点立场领域兴趣 存入到交互表中')
    #     portrait = await extract_portrait(data  = interaction_records, platform = platform)
    #     self.log.info(f'提取出来的兴趣是：{portrait["top_interests"]}')
    #     self.log.info(f'提取出来的领域是：{portrait["top_fields"]}')
    #     # 更新账号account_id兴趣和历史兴趣到social_attributes表中
    #     await bot.update_account_interest(account_id=account_id,interest=portrait["top_interests"])
    #     self.log.info(f'已成功更新 social_attributes 表中账号 {account_id} 的兴趣和历史兴趣')
    #     bot.driver.quit()  # 关闭bot

    #     # 更新person表中的兴趣和领域字段和history字段([dict])
    #     database = sql_dataset(platform_to_db[platform])
    #     sql = f'''SELECT Person_id FROM accounts_info WHERE account_id = {account_id}'''
    #     character_id = database.get_dict_data_sql(sql)[0]["Person_id"]
    #     self.log.info(f'{platform}账号{account_id}对应的person_id是{character_id}, 更新person表中的兴趣和领域')
    #     update_sql = '''UPDATE person SET Interest = %s, Field = %s, History = %s WHERE Id = %s'''
    #     database.operation(update_sql,(str(portrait["top_interests"]),str(portrait["top_fields"]),history,character_id))
    #     await asyncio.sleep(2)
    #     self.log.info(f'已成功更新 person 表中账号 {account_id} 的兴趣和领域')

    #     # 更新 platform_interaction 表中，交互帖子的观点立场和领域
    #     for item in portrait["content_view_field"]:
    #         for record in interaction_records:
    #             if item["content"] == record["content"]:
    #                 # 更新content_view_field表中的content和interaction_records
    #                 update_view = '''UPDATE {platform_to_db[platform]}_interaction SET Opinion_stand = %s, Field = %s, Interest = %s WHERE Account_id = %s AND URL = %s AND Action = %s'''
    #                 database.operation(update_view,(str(item["view"]),str(item["field"]),account_id,record["url"],record["action"]))
    #     self.log.info(f'已更新 {platform}_interaction 表中交互记录的观点立场和领域')



async def  update_multiple_platforms(platforms_accounts):
    '''按照账号顺序执行，每个账号完成后再执行下一个，平台之间仍然串行'''
    for platform, accounts in platforms_accounts.items():
        log.info(f"开始平台 {platform} 的账号处理")
        for account_id in accounts:
            updater = UpdateCharacter(platform, account_id, log_path=f"./logs/update_character/{platform}/{account_id}/update_character_log.log")
            log.info(f"开始处理平台 {platform} 的账号 {account_id}")
            await updater.extract_and_update_interest()  # 更新兴趣
            await updater.extract_and_update_field()  # 更新领域
            await updater.extract_and_update_view()  # 更新观点
            log.info(f"完成平台 {platform} 的账号 {account_id} 处理")
            await asyncio.sleep(1)  # 账号之间短暂间隔
        log.info(f"完成平台 {platform} 的账号处理\n")
        await asyncio.sleep(3)  # 每个平台之间等3秒vv
    


# 主函数
async def update_character_main():
    # 定义多个平台和每个平台下的账号
    platforms = ["twitter","facebook","douyin","kuaishou","toutiao","weibo","bilibili","xiaohongshu"]
    # 构建 平台 和账号映射
    platforms_accounts = {}
    for platform in platforms:
        select_sql = f'''SELECT Account_id FROM accounts_info'''
        database = sql_dataset(platform_to_db[platform])
        results = database.get_dict_data_sql(select_sql)
        accounts = [item["Account_id"] for item in results if item]
        platforms_accounts[platform] = accounts
    
    # # twitter平台 以 67 为例
    # platforms_accounts = {"twitter":[67]}
    # 更新多个平台和账号
    await update_multiple_platforms(platforms_accounts)


def run_scheduler():
    '''一周启动一次update_character_main函数'''
    # 获取当前时间
    current_time = datetime.datetime.now()
    asyncio.run(update_character_main())  # 启动一次

    while True:
        # 计算一周后的时间
        next_run_time = current_time + datetime.timedelta(weeks=1)
        # 设置要执行的时间段
        start_time = next_run_time.replace(second=0, microsecond=0)  # 一周后的整点
        end_time = start_time + datetime.timedelta(minutes=20)  # 20分钟内

        log.info(f'main函数启动时间是：{start_time.strftime("%Y-%m-%d %H:%M:%S")}-{end_time.strftime("%Y-%m-%d %H:%M:%S")}')

        # 每5分钟检查一次任务是否要执行
        while True:
            # schedule.run_pending()
            # 获取当前时间
            now = datetime.datetime.now()
            log.info(f'当前时间是：{now.strftime("%Y-%m-%d %H:%M:%S")},等待到达{start_time.strftime("%Y-%m-%d %H:%M:%S")}')
            
            # 如果当前时间在目标时间段内，执行main函数
            if start_time <= now <= end_time:
                # 更新current_time为当前时间，准备下次计算下一个周期
                current_time = datetime.datetime.now() 
                # 启动
                asyncio.run(update_character_main())  
                break
            log.info(f'等待到达时间...')
            time.sleep(300)  # 每5分钟检查一次



# 运行主函数
if __name__ == "__main__":
    # asyncio.run(update_character_main())
    run_scheduler()