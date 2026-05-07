import os
import sys
pythonpath = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0,pythonpath)
from datetime import datetime
from utils.prompt import prediction_action,GENERAL_PLAN,filter_interested_content,filter_interested_content_from_following
from utils.generation import general_generation
import json
from utils.sql import sql_dataset
import pdb
from datetime import timedelta
import random
import asyncio  
# D:\CODE\agentcode\Agent_923\planner\weibo_planner.py
from xhs_agent.xhs_bot import XiaohongshuBot
from utils.log import logger
from utils.utils import timer, download_image,find_txt_and_images
from pathlib import Path
import time
from weibo_agent.weibo_bot import WeiboBot
class XiaohongshuPlanner:
    def __init__(self,log_path = './logs/planner/planner_log.log'):
        self.log_path = log_path
        self.log = logger(filename=self.log_path)
        self.database = sql_dataset('xiaohongshu')
       
    async def get_topics_information(self,topic_path=None):
        '''获取话题池'''
        topics_information= []
        with open(topic_path,'r',encoding='utf-8') as f:
            topics_information = json.load(f)
        # self.log.info(f'获取的话题信息是：{topics_information}')
        return topics_information




    def fomat_action_time(self,action_times):
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
            if result["post_time"] == "Unknown" or result["post_time"] =='':
                continue
            post_time = datetime.strptime(result["post_time"], '%Y-%m-%d %H:%M')   
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
        return final_result   # 返回的是： [{'date': '2024-09-18', 'weekday': 'Wednesday', 'detail': ['00:40', '02:08', '11:35', '13:33', '16:08', '18:34', '23:35']},]
    
   
    async def get_history(self,url:str):
        """
        获取人物历史的行为数据
        """
        self.log.info(f"开始获取人物历史的行为数据")
        driver = XiaohongshuBot()
        await driver.login_by_cookies(account_id=1)
        # driver.login(account_id=1)
        results = await driver.get_all_content(url=url,time_limit=30)
        self.log.info(f"获取到的人物历史的行为数据为：{results}")
        return results


    async def get_prediction_time(self,url:str,account_id:int,history=None):
        '''
        预测账户的操作时间
        如果是仿人物
        1.获取人物历史的行为数据
        2.提取时间序列并排序
        3.预测账号未来一周的活跃时间
        如果是普通账户：直接预测
        '''
        self.log.info(f"输入的信息为url={url},account_id={account_id},history={history}，开始预测账户{account_id}操作时间")
        # self.log.info(f"开始预测账户{account_id}操作时间")
        if url is not None and history:
            formatted_time = self.format_time(history)
            self.log.info(f"提取到的时间序列：{formatted_time}")
            today = datetime.now()#.strftime("%Y-%m-%d %H:%M:%S")
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
            today = datetime.now()#.strftime("%Y-%m-%d %H:%M:%S")
            self.log.info(f"当前时间：{today}")
            for i in range(7):
                predict_time = (today + timedelta(days=i)).strftime("%Y-%m-%d")
                imitation_prompt = prediction_action(f'{predict_time}')
                response = await general_generation([{"role":"system","content":GENERAL_PLAN},{"role":"user","content":f'''{predict_time}'''}])
                self.log.info(f"预测的{predict_time}的活跃时间为：{response}")
                response = eval(response)
                # 对response进行后处理，如果detail大于1，则随机选择一个时间，确保一天只活跃一次
                details = response["detail"]
                if len(details) > 1:
                    response["detail"] = random.sample(details,1)
                outputs.append(response)
        self.log.info(f"预测的未来一周的活跃时间为：{outputs}")
        sql = '''UPDATE accounts_info SET Prediction_Action_Time = %s WHERE Account_id = %s'''
        self.database.operation(sql,(json.dumps(outputs),account_id,))

        return outputs
    



    async def get_xingyun_picture(self,account):
        '''从微博 星云大师 获取图片'''

        
        current_date = datetime.now().strftime("%Y-%m-%d")  # 获取当前日期
        # 图片保存路径
        save_path = f'./information/xhs_images/{current_date}'
        image_path = f'{save_path}/image/image_0.jpg'
        if os.path.exists(image_path):
            self.log.info(f'{image_path}图像存在，不需要从星云大师微博爬取，可直接使用')
            save_path = Path(save_path).resolve()
            txt_contents , image_paths = find_txt_and_images(root_path=save_path)
            return image_paths  # 返回绝对路径，list
        else:
            self.log.info(f'{image_path}图像不存在，需要从星云大师微博获取图片')
            weibo = WeiboBot(log_path=f'./logs/xhs/{account}/xhs_log.log')
            self.log.info('进入星云大师微博获取图片')
            result = await weibo.scrap_content(account_id=8,url='https://weibo.com/u/3172918062',num=1)
            result = json.loads(result.body.decode()).get("response")
            weibo.driver.quit()
            time.sleep(2)
            if isinstance(result,str):
                self.log.info(f'未能从星云大师的微博账号获得有效的微博内容，将返回存在的最早日期的图片')
                latest_iamge = self.find_latest_image_0(base_dir='./information/xhs_images')
                return [latest_iamge]  # 返回一个list
            elif isinstance(result,list):
                self.log.info(f'从星云大师微博获得的一条微博内容为：{result}')
                os.makedirs(f'./information/xhs_images/{current_date}',exist_ok=True)
                for index, image_url in enumerate(result[0]["images_url"]):
                    os.makedirs(f'{save_path}/image',exist_ok=True)
                    image_save_path = f'{save_path}/image/image_{index}.jpg'
                    download_image(image_url,image_save_path)
                # 返回图片的绝对路径
                save_path = Path(save_path).resolve()
                txt_contents , image_paths = find_txt_and_images(root_path=save_path)
                return image_paths  # 返回一个list,图像的绝对路径
        return []


    def find_latest_image_0(self,base_dir='./information/xhs_images'):
        base_dir = os.path.abspath(base_dir)
        latest_date = None
        latest_path = None

        for folder in os.listdir(base_dir):
            folder_path = os.path.join(base_dir, folder)
            if not os.path.isdir(folder_path):
                continue
            try:
                folder_date = datetime.strptime(folder, '%Y-%m-%d') # 日期文件夹 2025-01-18
            except ValueError:
                continue  # 忽略非日期命名的文件夹

            image_path = os.path.join(folder_path, 'image', 'image_0.jpg')
            if os.path.isfile(image_path):
                if latest_date is None or folder_date > latest_date:
                    latest_date = folder_date
                    latest_path = os.path.abspath(image_path)

        return latest_path
