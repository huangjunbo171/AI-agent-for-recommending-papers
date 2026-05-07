
import os
import sys
pythonpath = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0,pythonpath)
import time
from base_bot.base_bot import WebDriver
import os
from base_bot.email_bot import FirstmailBot
import re
from utils.utils import convert_time_us
from utils.log import logger
import pdb
import requests
import asyncio
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
from twitter_agent.twitter_bot import TwitterBot
from utils.sql import sql_dataset
import json
from datetime import datetime, timedelta
# from generation import generation_post,generation_comment
import pyperclip
from http import HTTPStatus
from twitter_agent.twitter_request import create_response
from datetime import datetime, timezone, timedelta
from utils.generation import *
from utils.prompt import *
class DeBot():
    def __init__(self, account:str,password:str,log_path: str = "./logs/debot/debot_log.log"):
        """
        初始化TwitterBot类的实例。

        参数：
        - log_path：日志文件路径，默认为 father_directory/log/twitter_log.log

        返回值：
        无
        """
        super().__init__()
        self.account = account
        self.password = password
        # self.driver = TwitterBot(log_path=log_path)
        self.driver = WebDriver(log_path=log_path) 
        self.log = logger(filename=log_path)
        self.database = sql_dataset('twitter')
    


    


    def login_by_account(self,url='https://debot.ai/deFiBot/strategy?chain=bsc'):
        '''登录debot'''

        try:
            self.driver.get(url=url)
            time.sleep(random.uniform(10,15))
            pdb.set_trace()
            try:
                self.driver.find_xpath(XPATH='//div[@class="MuiDialogContent-root modernize-zoikgh"]')
                self.log.info(f'存在通知框，点击 关闭')
                self.driver.search_and_click(XPATH='//div[@class="MuiDialogContent-root modernize-zoikgh"]//button[1]',waiting_time=3.0)
            except:
                pass
            self.log.info(f'点击登录')
            self.driver.search_and_click(XPATH='//button[text()="登录"]',waiting_time=3.0)
            self.log.info(f'输入账号')
            self.driver.search_and_click(XPATH='//input[@class="MuiInputBase-input MuiOutlinedInput-input modernize-1ma0cvp"]',waiting_time=1.0)
            self.driver.send_content(XPATH='//input[@class="MuiInputBase-input MuiOutlinedInput-input modernize-1ma0cvp"]',content=account)
            time.sleep(random.uniform(2,5))
            self.log.info(f'点击发送 验证码')
            self.driver.search_and_click(XPATH='//div[text()="发送验证码"]',waiting_time=2.0)
            self.log.info(f'登录邮箱：{account}')
            self.driver.open_new_tab(url='')
            time.sleep(random.uniform(1,3))
            self.driver.swith_to_new_window(id=-1)
            time.sleep(2)

            code = self.get_gmx_email_code()

            self.log.info(f'获得的验证码是：{code}')
            self.driver.close()
            time.sleep(2)
            self.driver.swith_to_new_window(id=0)
            time.sleep(2)
            self.log.info(f'输入验证码：{code}')
            self.driver.search_and_click(XPATH='//input[@name="loginCode"]',waiting_time=1.0)
            self.driver.send_content(XPATH='//input[@name="loginCode"]',content=code)
            self.log.info(f'点击 接受服务条款和隐私条款')
            self.driver.search_and_click(XPATH='//input[@aria-label="Checkbox demo"]',waiting_time=2.0)
            self.log.info(f'点击 登录')
            # self.driver.search_and_click(XPATH='//button[@id=":r15:"]',waiting_time=random.uniform(10,15))
            self.log.info(f'登录成功')

        except Exception as e:
            self.log.error(f"登录失败: {e}")
            return False
     

    def get_gmx_email_code(self,):
        '''登录gmx邮箱，获取验证码'''
        try:
            self.driver.get(url='https://www.gmx.com/')
            time.sleep(random.uniform(15,20))
            try:
                self.driver.search_and_click(XPATH='//button[@class="icon-close js-close" and @aria-label="Close layer"]',waiting_time=2.0)
            except:
                pass
            self.log.info(f'点击 登录按钮')
            self.driver.search_and_click(XPATH='//a[@class="button button-login" and @aria-label="Log in"]',waiting_time=5.0)
            self.log.info(f'输入账号：{self.account}')
            self.driver.send_content(XPATH='//input[@id="login-email" and @name="username"]',content=self.account)
            time.sleep(1)
            self.log.info(f'输入密码：{self.password}')
            self.driver.send_content(XPATH='//input[@id="login-password" and @name="password"]',content=self.password)
            time.sleep(1)
            self.log.info(f'点登录按钮')
            self.driver.search_and_click(XPATH='//button[@class="btn btn-block login-submit" and @type="submit"]',waiting_time=random.uniform(10,15))
            self.driver.driver.refresh()
            time.sleep(5)


            # self.driver.search_and_click(XPATH='//div[@title="Show/Hide more folders"]',waiting_time=2.0)
            # time.sleep(2)

            self.driver.switch_to_frame(XPATH='//iframe[@id="thirdPartyFrame_mail"]')
            time.sleep(2)
            self.log.info(f'点击第一封邮件')
            self.driver.search_and_click(XPATH='//tbody[@data-oao-page="0"]/tr[@class="new"]',waiting_time=5.0)
            self.driver.switch_to_frame(XPATH='//iframe[@id="mail-detail"]')
            time.sleep(2)
            code = self.driver.find_xpath(XPATH='//h1').text

            return code
        except Exception as e:
            self.log.error(f'获取邮箱 {self.account} 验证码失败，原因是：{e}')


    def within_3min(self,s: str, now: datetime | None = None) -> bool:
        """
        s 例子: "10/16 16:40:52"
        返回该时间是否与当前时间相差不超过 3 分钟（绝对值）。
        """
        now = now or datetime.now()  # 用本机当前时间（含本地时区）
        # 先按无年份解析
        t = datetime.strptime(s, "%m/%d %H:%M:%S")
        # 补上当前年份
        dt = t.replace(year=now.year)

        # 处理跨年（例如 01/01 相对 12/31 的前一天）
        if dt - now > timedelta(days=183):      # 过于“将来”，认为应是去年
            dt = dt.replace(year=now.year - 1)
        elif now - dt > timedelta(days=183):    # 过于“过去”，认为应是明年
            dt = dt.replace(year=now.year + 1)

        return abs((now - dt).total_seconds()) <= 180


    async def get_debot_notify_messagee(self,account_ids:list):
        '''获得监控的消息'''
        try:
            # 登录debot
            # await self.login_by_account()

            pdb.set_trace()  # 先手动登录一下debot
            self.log.info(f'点击 通知消息')
            self.driver.search_and_click(XPATH='//a[@href="/deFiBot/notifications"]',waiting_time=5.0)
   
            while True:
                self.driver.driver.refresh()
                await asyncio.sleep(random.uniform(5,10)) 
                try:
                    first_article = self.driver.find_xpath(XPATH='//div[@class="MuiStack-root modernize-5ax1kt"]')
                except:
                    self.log.info(f'暂时不存在新的消息通知，等待 3min 刷新')
                    time.sleep(3 * 60)
                    continue
                
                time_str = first_article.text.split('\n')[0]
                # time_str = '10/28 15:40:04'
                user_name = first_article.text.split('\n')[2].replace('@','')
                post_content = first_article.text.split('\n')[-2]  # 贴文内容

                # 比较时间，时间如果是和现在时间相差小于三分钟，则记录，并评论
                if not self.within_3min(time_str):
                    self.log.info(f'该条通知不在三分钟之内，继续等待3min')
                    time.sleep(3*60)
                    continue
                    
                self.log.info(f'该条通知在三分钟之内，到账号{user_name}的最新帖子进行评论')
                # 点击 “查看原帖”
                post_url = first_article.find_element(By.TAG_NAME,'a').get_attribute("href")
                # 在新的页面登录账号
                for account_id in account_ids:
                    bot =  TwitterBot(log_path=f'./logs/twitter/{account_id}/twitter_log.log')
                    await bot.login_by_cookies(account_id=int(account_id))
                    # 进入原帖链接
                    bot.driver.get(url=post_url)
                    await asyncio.sleep(random.uniform(5,10)) 
                    # 根据人设生成内容，并评论
                    # character = self.get_account_character(account_id=account_id)
                    
                    # 工作当作人设？
                    search_sql = f"SELECT * FROM accounts_info WHERE accounts_info.Account_id = {account_id}"
                    character_id = self.database.get_dict_data_sql(search_sql)[0]['Person_id']
                    if character_id: # 获取人设
                        character_sql = f"SELECT * FROM person WHERE person.Id = {character_id}"
                        character = self.database.get_dict_data_sql(character_sql)[0]["Job"]
                    
                    _,comment_content =  await general_generation_think([{"role": "system", "content":  comment_post_prompt(character=character)},
                                                            {"role": "user", "content": f'''贴文内容是： {post_content} ''' }])
                    self.log.info(f'模型生成的内容是：{comment_content}')
                    comment_content  =  self.cut_content(comment_content,260)
                    # 评论
                    await bot.comments(account_id=account_id,url=post_url,content = comment_content)
                    # 关闭当前窗口
                    bot.driver.quit()
                    await asyncio.sleep(random.uniform(2,5)) 
                
        except Exception as e:
            self.log.info(f'获得监控消息失败，原因是：{e}')



    def get_account_character(self,account_id):
        '''获取账号account_id的人设'''
        # 获取账号人设
        search_sql = f"SELECT * FROM accounts_info WHERE accounts_info.Account_id = {account_id}"
        character_id = self.database.get_dict_data_sql(search_sql)[0]['Person_id']
        if character_id: # 获取人设
            character_sql = f"SELECT * FROM person WHERE person.Id = {character_id}"
            character = self.database.get_dict_data_sql(character_sql)[0]["Description"]
        else:
            character = '专心科研的学者，经常在社交平台发布论文相关的内容'
        return character
    


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

if __name__ == '__main__':
    # account = 'beckah-kawaa@gmx.com'
    # password = 'yCyPTpjwQ3'   # 测试账号,


    # account = 'ros27rainbow@gmx.com'   # @Alibaba_Qwen  @OpenAI
    # password = 'z0gharSpk'

    # account = 'al485cori@gmx.com'  #AIatMeta  @GoogleDeepMind
    # password = 'o7nRBCcz6'

    # account = 'demaseehqgarey@gmx.com'    # AnthropicAI   Meta
    # password = 'jsTjcsaw5'


    account = 'martiheyes2005@gmx.com'    # claudeai  XAI
    password = 'ntfkvJY6er'
    
    bot = DeBot(account=account,password=password,log_path=f'./logs/debot/{account}/debot_log.log')
    asyncio.run(bot.get_debot_notify_messagee(account_ids=[1,224]))

#  https://debot.ai/deFiBot/strategy?chain=bsc