
import os
import sys
pythonpath = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0,pythonpath)
import time
from base_bot.base_bot import WebDriver
import os
import re
from utils.utils import convert_time_us
from utils.log import logger
import pdb
from dateutil.relativedelta import relativedelta
from urllib.parse import urljoin
from dateutil import parser
from selenium.webdriver.common.action_chains import ActionChains
# usage有 reply_comment comment transmit post
# 衍生的附加属性 post_content comment_content
from bs4 import BeautifulSoup
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
import threading
import random 
import string
from utils.sql import sql_dataset
import json
from datetime import datetime, timedelta
# from generation import generation_post,generation_comment
import pyperclip
from http import HTTPStatus
from .twitter_request import create_response

class ScrapNewsBot():
    def __init__(self, log_path: str = "./logs/scrap_news/scrap_news.log"):
        """
        初始化TwitterBot类的实例。

        参数：
        - log_path：日志文件路径，默认为 father_directory/log/twitter_log.log

        返回值：
        无
        """
        super().__init__()
        self.driver = WebDriver(log_path=log_path,use_proxy=True,headless=True )  # 无头模式 ,headless=True 
        self.log = logger(filename=log_path)
        self.database = sql_dataset('twitter')

    def is_relative_time(self,time_str):
        '''判断是否是相对时间'''
        relative_time_patterns = [
            r'(\d+)\s*minutes? ago',
            r'(\d+)\s*hours? ago',
            r'(\d+)\s*days? ago'
        ]
        for pattern in relative_time_patterns:
            if re.search(pattern, time_str):
                return True
        return False

    def parse_relative_time(self,relative_time_str):
        '''
        解析相对时间，转换成实际发布时间
        返回:解析后的datetime
        '''
        # 获取当前的时间
        now_time = datetime.now()

        # 正则
        time_patterns = {
            'minute': re.compile(r'(\d+)\s*minutes? ago'),
            'hour': re.compile(r'(\d+)\s*hours? ago'),
            'day': re.compile(r'(\d+)\s*days? ago')
        }
        for unit, pattern in time_patterns.items():
            match = pattern.search(relative_time_str)
            if match:
                value = int(match.group(1))
                if unit == 'minute':
                    return now_time - relativedelta(minutes=value)
                elif unit == 'hour':
                    return now_time - relativedelta(hours=value)
                elif unit == 'day':
                    return now_time - relativedelta(days=value)


    def parse_exact_date(self,date_str):
        '''解析具体日期'''
        try:
            return parser.parse(date_str)
        except ValueError:
            return None


    def parse_time_str(self,time_str):
        '''解析时间'''
        if self.is_relative_time(time_str):
            # 解析相对时间
            post_time = self.parse_relative_time(time_str)
        else:
            # 解析绝对时间
            post_time = self.parse_exact_date(time_str)
        return post_time  # 返回datetime类型的时间
    
    def get_topic_content_from_bbc(self,account_id):
        '''
        从bbc新闻网站上获取话题
        返回：topic_content[dict]     [{'topic':'', 'content':'', 'post_time':''}]
        '''
        news = {} 
        topic_content = []
        current_date = datetime.now().strftime("%Y-%m-%d")  # 获取当前日期
        try:
            self.driver.get('https://www.bbc.com/news/us-canada')  # 进入bbc官网
            time.sleep(10)
            # 滚动页面
            self.driver.scroll(size=200)
            time.sleep(2)
            # pdb.set_trace()
            self.log.info('选择最新的新闻')
            # 循环所有的页面
            for button in range(1,2):  # 只获取前2页的内容、
                # 显示等待 新闻面板
                latest_element = WebDriverWait(self.driver.driver,10).until(
                    EC.presence_of_element_located((By.XPATH,'//div[@data-testid="alaska-section"]'))
                )
                liverpool_elements_num = len(latest_element.find_elements(By.XPATH,'.//div[@data-testid="liverpool-card"]')) # 9
                # 循环所有的新闻，点击进新闻，并获取相关内容
                for index in range(liverpool_elements_num):  # 从0到8
                    liverpool_elements = self.driver.find_xpaths(XPATH='//div[@data-testid="liverpool-card"]')  # 新闻列表
                    time.sleep(5)
                    # 获取新闻标题
                    topic_item = liverpool_elements[index].find_element(By.XPATH,'.//h2[@data-testid="card-headline"]').text
                    topic_item = topic_item.replace('"', '').replace("'", '').replace('“', '').replace("”", '').replace("‘", '').replace("’", '')
                    self.log.info(f'开始获取第{(button-1)*liverpool_elements_num+index+1}个新闻的内容')
                    liverpool_elements[index].click()   # 进入新闻界面
                    time.sleep(5)
                    self.driver.driver.refresh()
                    time.sleep(3)
                    # 获取新闻内容
                    try:
                        # 发布的是视频内容   data-testid="video-page-player"
                        self.driver.find_xpath(XPATH='//div[@data-testid="video-page-player"]')  # 如果找到了视频元素
                        time.sleep(2)
                        self.log.info('是视频新闻，获取视频简介内容和时间')
                        # 先找到h1
                        note_form = '视频新闻'
                        h1_element = self.driver.driver.find_element(By.CSS_SELECTOR,'h1')
                        time.sleep(2)
                        div_element = h1_element.find_element(By.XPATH,'following-sibling::div')   # sc-9b10f25c-3 cdaUmY
                        time.sleep(2)
                        content = div_element.text.replace('\n','')
                        time_str = div_element.find_element(By.XPATH,'following-sibling::span').text
                        time.sleep(2)
                        post_time = self.parse_time_str(time_str).strftime('%Y-%m-%d %H:%M:%S') # 解析时间为字符串
                    except Exception as e:
                        # 文本新闻
                        try:
                            time_str_element = self.driver.find_xpath(XPATH='//time')  # time_str元素
                            time.sleep(3)
                            self.log.info('是文本新闻，获取新闻内容和时间')
                            time_str = time_str_element.text
                            note_form = '文本新闻'
                            post_time = self.parse_time_str(time_str).strftime('%Y-%m-%d %H:%M:%S') # 解析时间为字符串
                            # 获取新闻文本
                            text_block_elements = self.driver.find_xpaths(XPATH='//div[@data-component="text-block" and @class="sc-18fde0d6-0 dlWCEZ"]')
                            time.sleep(3)
                            content = ''  # 初始化一个空的content
                            for text_block_element in text_block_elements:
                                content = content + text_block_element.text.replace('\n','') 
                        except Exception as e:
                            self.log.info(f'查找新闻内容的时候出现错误:{e}')
                    # 添加进列表，后续写入文件保存
                    time.sleep(3)
                    # 去掉引号
                    content = content.replace('"', '').replace("'", '').replace('“', '').replace("”", '').replace("‘", '').replace("’", '')
                    # 获取新闻的链接
                    news_url = self.driver.driver.current_url
                    news = {'news': topic_item, 'content': content, 'post_time': post_time,"content_url":news_url}
                    self.log.info(f"bbc新闻内容为：{news}")
                    topic_content.append(news)
                    # 写入文件
                    os.makedirs(f"./information/bbc_news/", exist_ok=True)
                    with open(f"./information/bbc_news/{current_date}.json","a",encoding="utf-8") as file:
                        file.write(json.dumps(news, ensure_ascii=False) + "\n")

                    # 存入twittert的曝光数据表中
                    insert_sql = '''INSERT INTO `twitter_records`(`Account_id`,`Platform`,`URL`,`Content`,`Published_Time_IP`,`Form`,`Update_time`) VALUES(%s,%s,%s,%s,%s,%s,%s);'''
                    self.database.operation(insert_sql,(account_id,'bbc',news_url,topic_item + content,post_time,note_form,datetime.now()))
                    self.log.info('已更新twitter内容曝光表')

                    self.log.info(f'该新闻的时间是：{post_time}')
                    self.log.info('回到最开始的页面')
                    self.driver.get('https://www.bbc.com/news/us-canada')
                    # self.driver.go_back()
                    time.sleep(5)
                    # 点击相应的页面按钮
                    # 查看当前是否是button页
                    page_id = self.driver.find_xpath(XPATH='//button[@data-testid="pagination-back-button"]').text
                    self.log.info(f'当前在第{page_id}页，实际应该在第{button}页')
                    if int(page_id) == button:
                        continue # 是当前页，继续查找新闻
                    else:
                        # 点击到button页再查找新闻
                        self.driver.search_and_click(XPATH=f'//button[@class="sc-faaff782-1 sc-faaff782-2 dScmQm hPrIkI" and text()="{button}"]',waiting_time=2.0)
                        self.log.info(f'已经跳转到第{button}页，继续获取新闻内容')
                
                news_panel = self.driver.find_xpath(XPATH='//div[@class="sc-da05643e-0 kbaPPZ"]')   # 整个新闻面板
                # 点击下一页的按钮
                news_panel.find_element(By.XPATH,'.//button[@data-testid="pagination-next-button" and @aria-label="Next Page"]').click()
                time.sleep(5)
                self.log.info(f'第{button}页的话题已经获取完毕,进入到第{button+1}页继续获取新闻')
            return topic_content 
        except Exception as e:
            self.log.info(f'获取新闻失败:',{e}) 
            return []  # 空的列表[字典]  
        

    def get_topic_content_from_cnn(self,account_id,num:int=10):
        '''
        从cnn网站上获取最新的美国政治新闻, 共能获取到46个新闻，随机选择10个
        返回：topic_content = [{'news': topic_item, 'content': content, 'post_time': post_time,"content_url":news_url}]
        '''
        
        news = {}
        topic_content = []
        urls_set = set()
        current_date = datetime.now().strftime("%Y-%m-%d")  # 获取当前日期
        try:
            self.driver.get(url = 'https://edition.cnn.com/politics') # CNN-> politics板块，获取latest新闻
            time.sleep(random.uniform(10,20))
            # 找到所有的a元素
            a_elements = self.driver.find_xpaths(XPATH='//a[@data-link-type="article"]')
            # 循环所有的a_element，保存其链接
            for a_element in a_elements:
                url = a_element.get_attribute("href")
                urls_set.add(url) 

            urls_list = list(urls_set)
            urls_list = random.sample(urls_list,num)  # 随机选择10个CNN新闻
            if urls_list:
                # 输出所有的链接
                self.log.info(f'从CNN上共获取到{len(urls_list)}个新闻链接')
                for url in urls_list:
                    self.log.info(f'获取第{urls_list.index(url)+1}条新闻{url}的内容')
                    self.driver.get(url = url)
                    time.sleep(random.uniform(8,15))
                    # 获取新闻标题
                    topic = self.driver.find_xpath(XPATH='//h1[@data-editable="headlineText"]').text
                    # 获取新闻发布时间,Updated 9:15 PM EDT, Thu September 19, 2024
                    try:
                        first_published_time = self.driver.find_xpath(XPATH='//span[@class="timestamp__time-since"]').get_attribute("data-first-publish")
                    except:
                        try:
                            first_published_time = self.driver.find_xpath(XPATH='//div[@class="timestamp vossi-timestamp"]').text.replace('\n','')
                        except:
                            first_published_time = ''
                    # 获取新闻内容
                    content = self.driver.find_xpath(XPATH='//div[@class="article__content"]').text.replace('\n','')
                    # 去掉引号
                    content = content.replace('"', '').replace("'", '').replace('“', '').replace("”", '').replace("‘", '').replace("’", '')
                    news = {'news': topic, 'content': content, 'post_time': first_published_time,"content_url": url}
                    self.log.info(f"cnn新闻内容为：{news}")
                    topic_content.append(news)
                    # 存入twittert的曝光数据表中
                    insert_sql = '''INSERT INTO `twitter_records`(`Account_id`,`Platform`,`URL`,`Content`,`Published_Time_IP`,`Update_time`) VALUES(%s,%s,%s,%s,%s,%s);'''
                    self.database.operation(insert_sql,(account_id,'bbc',url,topic + content,first_published_time,datetime.now()))
                    self.log.info('已更新twitter内容曝光表')
                    os.makedirs(f"./information/cnn_news/", exist_ok=True)
                    with open(f"./information/cnn_news/{current_date}.json","a",encoding="utf-8") as file:
                        file.write(json.dumps(news, ensure_ascii=False) + "\n")
            return topic_content
        except Exception as e:
            self.log.info(f'获取新闻失败:',{e}) 
            return topic_content  # 空的列表[字典] 
        
