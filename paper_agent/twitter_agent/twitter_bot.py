
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
from utils.sql import sql_dataset
import json
from datetime import datetime, timedelta
# from generation import generation_post,generation_comment
import pyperclip
from http import HTTPStatus
from twitter_agent.twitter_request import create_response
from datetime import datetime, timezone, timedelta
class TwitterBot():
    def __init__(self, log_path: str = "./logs/twitter/twitter_log.log"):
        """
        初始化TwitterBot类的实例。

        参数：
        - log_path：日志文件路径，默认为 father_directory/log/twitter_log.log

        返回值：
        无
        """
        super().__init__()
        self.driver = WebDriver(log_path=log_path,use_proxy=True ,headless=True)   # ,headless=True
        self.log = logger(filename=log_path)
        self.database = sql_dataset('twitter')
        
        
    async def login(self, url: str = "https://twitter.com/?lang=zh", account_id = None):
        
        "利用账号和密码登录，可能需要验证，用cookie登录用self.driver._login"
        '''下一步优化是：只传入帐号id，然后去数据库查询获取帐号信息'''
        try:
            search_sql = f"SELECT * FROM accounts_info WHERE accounts_info.Account_id = {account_id}"
            result = self.database.get_dict_data_sql(search_sql)[0]
            self.log.info("从数据库中获取到的账号信息:{}".format(result))
            account = result['Account']
            password = result['Password']
            email = result['Email']
            email_password = result['Email_password']
            cookies = result['Cookie']
            FAcode = result['2FAcode']
            token = result['Token']
            avatar_url = result['Avatar_url']
        except Exception as e:
            self.log.error("获取账号信息失败，原因：{}".format(e))
            raise Exception("获取账号信息失败")
        try:
            if cookies:
                cookies = json.loads(cookies)

            # cookies = {}
            # token = 'b4827951eab5c405e22440b52e3de6088da7407b'
            # self.driver._login(url="https://x.com/home",token=token)

            self.driver._login(url="https://x.com/home",cookies=cookies,token=token)
            time.sleep(random.uniform(15,30))
            # pdb.set_trace()

            #检查是否登录成功,是否包含帐号
            self.handle_email_verify(email=email,email_password=email_password)
            time.sleep(random.uniform(5,15))
            self.driver.find_xpath(XPATH=f"//span[contains(text(), '{account}')]")
            self.log.info("利用cookies或token登录成功")  
            suspened = self.driver.find_xpaths(XPATH="//span[contains(text(), 'Your account is suspended')]")
            if suspened:
                self.log.info("账号被冻结了")
                with open(f"./information/suspended_accounts.txt","a",encoding="utf-8") as file:
                    file.write(result + "\n")
                return
            if not cookies:
                new_cookies = json.dumps(self.driver.get_cookies(url="https://x.com/home"))
                self.log.info("获取新cookies")
                sql = '''UPDATE accounts_info SET Cookie = %s, Cookie_status = %s, Platform = %s,Latest_login_time = %s WHERE Account_id = %s;'''
                self.database.operation(sql,(new_cookies,'在线','twitter',datetime.now(),account_id))
                time.sleep(random.uniform(1,3))
                self.log.info("更新数据库cookies成功")    
            await self.get_user_profile(account_id=account_id)
            time.sleep(2)
            self.log.info(f'更新账号社交属性成功')
            sql = '''UPDATE accounts_info SET Cookie_Status = %s WHERE Account_id = %s;'''
            self.database.operation(sql,('在线',account_id))

        except:
            try:
                self.log.info("加载cookies登录失败，尝试账号密码登录")
                self.driver.get(url)
                self.log.info("进入推特")
                time.sleep(random.uniform(8,15))
                self.driver.search_and_click(XPATH="//a[@role = 'link' and @href = '/login']")
                self.log.info("点击登录")
                time.sleep(random.uniform(8,15))
                self.driver.send_content(XPATH="//input[@name = 'text']", content = account)
                self.log.info("输入账号")
                time.sleep(random.uniform(2,4))
                self.driver.search_and_click(XPATH="//span[contains(text(), '下一步')]", waiting_time=1.0)
                self.log.info("点击下一步")
                time.sleep(random.uniform(8,15))
                try: 
                    self.driver.find_xpath(XPATH="//input[@data-testid='ocfEnterTextTextInput']")
                    self.log.info("出现验证，需要输入手机号/邮箱号验证")
                    # self.driver.search_and_click(XPATH="//input[@data-testid='ocfEnterTextTextInput']", waiting_time=1.0)
                    self.driver.send_content(XPATH="//input[@data-testid='ocfEnterTextTextInput']", content=email)
                    self.log.info("点击下一步")
                    self.driver.search_and_click(XPATH="//button[@data-testid='ocfEnterTextNextButton']", waiting_time=1.0)
                except:
                    self.log.info("不需要输入手机号/邮箱号验证")
                self.driver.send_content(XPATH="//input[@type = 'password']", content = password)
                self.log.info("输入密码")
                time.sleep(random.uniform(2,4))
                self.log.info("点击登录")
                self.driver.search_and_click(XPATH="//span[contains(text(), '登录')]", waiting_time=3.0)
                # try: 
                #     self.driver.find_xpath(XPATH="//input[@data-testid='ocfEnterTextTextInput']")
                #     self.log.info("需要输入手机号验证")
                #     # self.driver.search_and_click(XPATH="//input[@data-testid='ocfEnterTextTextInput']", waiting_time=1.0)
                #     self.driver.send_content(XPATH="//input[@data-testid='ocfEnterTextTextInput']", content=email)
                #     self.log.info("点击下一步")
                #     self.driver.search_and_click(XPATH="//button[@data-testid='ocfEnterTextNextButton']", waiting_time=1.0)
                # except:
                #     self.log.info("不需要输入手机号验证")
                try:
                    self.driver.find_xpath(XPATH="//input[@inputmode='numeric']")
                    code = self.get_2FAcode(FAcode)
                    time.sleep(random.uniform(2,4))
                    self.driver.send_content(XPATH="//input[@inputmode='numeric']", content = code)
                    self.log.info("输入2FA验证码:{}".format(code))
                    self.driver.search_and_click(XPATH="//button[@data-testid='ocfEnterTextNextButton']", waiting_time=5.0)
                except:
                    self.log.info("不需要代码生成器生成验证码")
                
                self.handle_email_verify(email=email,email_password=email_password)
                try:
                    self.driver.find_xpath(XPATH="//span[contains(text(), 'Your account is suspended')]")
                    self.log.info("账号被冻结了")
                    with open(f"./information/suspended_accounts.txt","a",encoding="utf-8") as file:
                        file.write(result + "\n")
                    return
                except:
                    self.log.info("账号正常")
                
                try:
                    time.sleep(random.uniform(2,4))
                    #检查是否登录成功,是否包含帐号
                    self.driver.find_xpath(XPATH=f"//span[contains(text(), '{account}')]")
                    self.log.info("登录成功")
                    suspened = self.driver.find_xpaths(XPATH="//span[contains(text(), 'Your account is suspended')]")
                    if suspened:
                        self.log.info("账号被冻结了")
                        with open(f"./information/suspended_accounts.json","a",encoding="utf-8") as file:
                            file.write(json.dumps(result,ensure_ascii=False)+ "\n")
                        return
                    new_cookies = json.dumps(self.driver.get_cookies(url="https://x.com/home"))
                    self.log.info("获取新cookies")

                    # 使用账号密码登录时，获取头像链接
                    try:
                        self.driver.get(url=f'https://x.com/{account}/photo')
                        time.sleep(random.uniform(10, 20))
                        avatar_url = self.driver.find_xpath(XPATH='//img[@alt="Image" and @class="css-9pa8cd"]').get_attribute('src')
                    except:
                        avatar_url = None
                    sql = '''UPDATE accounts_info SET Avatar_url = %s, Cookie = %s, Cookie_status = %s, Platform = %s,Latest_login_time = %s WHERE Account_id = %s;'''
                    self.database.operation(sql,(avatar_url,new_cookies,'在线','twitter',datetime.now(),account_id))
                    time.sleep(random.uniform(1,3))
                    await self.get_user_profile(account_id=account_id)
                    time.sleep(2)
                    self.log.info(f'更新账号社交属性成功')
                    self.log.info("更新数据库cookies成功")
                except Exception as e:
                    self.log.error("更新数据库cookies失败，原因：{}".format(e))
            except Exception as e:
                self.log.error("登录失败，原因：{}".format(e))         
    
    
    def get_2FAcode(self,FAcode):
        "获取2FA验证码"
        url = "https://2fa.guts.eu.org/{}".format(FAcode)   
        self.driver.open_new_tab(url)#打开新的标签页
        time.sleep(random.uniform(2,4))
        self.driver.swith_to_new_window(-1)#切换到新的标签页
        time.sleep(random.uniform(1,3))
        self.driver.get(url=url)
        code = self.driver.find_xpath(XPATH='//pre').text
        code = json.loads(code)
        self.log.info("获取2FA验证码成功:{}".format(code))
        self.driver.close()#关闭新的标签页
        self.driver.swith_to_new_window(0)
        time.sleep(random.uniform(2,4))
        return code["token"]            
   
    def handle_email_verify(self,email,email_password):
        try:
            self.driver.search_and_click(XPATH="//input[@class='Button EdgeButton EdgeButton--primary' and @value='Start']", waiting_time=5.0)
            self.log.info("点击开始邮箱验证")
        except:
            self.log.info("不需要点击开始验证按钮")
        try:
            self.driver.search_and_click(XPATH="//input[@class='Button EdgeButton--primary EdgeButton' and @value='Send email']", waiting_time=3.0)
            self.log.info("点击发送邮件")
        except:
            self.log.info("不需要点击发送邮件")
        try:
            self.driver.find_xpath(XPATH="//input[@class='Button EdgeButton--primary EdgeButton' and @value='Verify']")
            self.log.info("需要邮箱验证码")
            outlook = FirstmailBot()
            code = outlook.get_verify_code(account=email,password=email_password)
            # code = self.get_verify_code(email=email,email_password=email_password)
            self.driver.send_content(XPATH="//input[@placeholder='Enter Verification Code']", content = code)
            self.log.info("输入验证码:{}".format(code))
            self.driver.search_and_click(XPATH="//input[@class='Button EdgeButton--primary EdgeButton' and @value='Verify']", waiting_time=1.0)
            self.log.info("点击验证")
            self.driver.search_and_click(XPATH="//input[@class='Button EdgeButton EdgeButton--primary' and @value='Continue to X']", waiting_time=1.0)
            self.log.info("点击继续")
        except:
            self.log.info("不需要邮箱验证码")  
            
                      
                
    async def login_by_cookies(self, account_id :int, url: str = "https://twitter.com/?lang=zh"):
        '''使用cookies登录账号'''
        create_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            search_sql = f"SELECT * FROM accounts_info WHERE accounts_info.Account_id = {account_id}"
            result = self.database.get_dict_data_sql(search_sql)[0]
            self.log.info("从数据库中获取到的账号信息:{}".format(result))
            cookies = result['Cookie']
            token = result['Token']
            ct0 = result['Ct0']
            profile = result['URL']  # 主页链接
        except Exception as e:
            self.log.error("获取账号信息失败，原因：{}".format(e))
            # raise Exception("获取账号信息失败")
            return create_response(create_time=create_time,code=HTTPStatus.BAD_REQUEST,message='error',response=f'账号{account_id}cookies下线，利用cookies登录失败')
        try:
            
            if cookies:
                cookies = json.loads(cookies)
            else:
                cookies = [{"name": "auth_token", "path": "/", "value": token, "domain": ".x.com", "expiry": 1785316008, "secure": True, "httpOnly": True, "sameSite": "None"},{"name": "ct0", "path": "/", "value": ct0, "domain": ".x.com", "expiry": 1785316009, "secure": True, "httpOnly": False, "sameSite": "Lax"}]
            self.driver._login(url="https://x.com/home",cookies=cookies,token=token)
            #检查是否登录成功,是否包含帐号
            time.sleep(random.uniform(5,8))
            # 刷新页面
            # 检查是否登录成功，是否包含账号
            href = self.driver.find_xpaths(XPATH='//a[@aria-label="Profile"]')[-1].get_attribute("href")
            if profile and href != profile:
                self.log.info(f"数据库中的主页链接为{profile}，当前的主页链接为{href}，不一致")
                sql = '''UPDATE accounts_info SET Cookie_Status = %s WHERE Account_id = %s;'''
                self.database.operation(sql,('下线',account_id))
                time.sleep(random.uniform(2,4))
                self.log.error(f'账号{account_id}cookies下线，利用cookies登录失败')
                # raise ValueError  # 抛出异常
                return create_response(create_time=create_time,code=HTTPStatus.BAD_REQUEST,message='error',response=f'账号{account_id}cookies下线，利用cookies登录失败')
            else:
                self.log.info("利用cookies登录成功")
                sql = '''UPDATE accounts_info SET Latest_login_time = %s WHERE Account_id = %s;'''
                self.database.operation(sql,(datetime.now(),account_id))
                await self.get_user_profile(account_id=account_id)
                return create_response(create_time=create_time,code=HTTPStatus.OK,message='success',response=f'账号{account_id}cookies登录成功')    
        except:
            sql = '''UPDATE accounts_info SET Cookie_Status = %s WHERE Account_id = %s;'''
            self.database.operation(sql,('下线',account_id))
            time.sleep(random.uniform(2,4))
            self.log.error(f'账号{account_id}cookies下线，利用cookies登录失败')   
            return create_response(create_time=create_time,code=HTTPStatus.BAD_REQUEST,message='error',response=f'账号{account_id}cookies下线，利用cookies登录失败')
    
      
    async def login_by_verificationcode(self, account_id = None, code=None, url: str = "https://twitter.com/?lang=zh", ):
        time.sleep(random.uniform(2,4))
        create_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            self.driver.find_xpath(XPATH="//input[@inputmode='numeric']")
            # 获取验证码
            code_content = self.get_2FAcode(code)
            self.driver.send_content(XPATH="//input[@inputmode='numeric']", content = code_content)
            self.log.info("输入2FA验证码:{}".format(code_content))
            self.log.info("点击下一步")
            self.driver.search_and_click(XPATH="//button[@data-testid='ocfEnterTextNextButton']", waiting_time=5.0)
            # 将账号的2FA验证码更新到数据库中
            update_sql = '''UPDATE accounts_info SET 2FAcode = %s WHERE Account_id = %s'''
            self.database.operation(update_sql,(code,account_id))
        except:
            self.log.info("不需要2FA输入验证码")
        try:
            self.driver.find_xpath(XPATH='//span[contains(text(),"检查你的邮箱")]')
            self.log.info(f'输入邮箱验证码:{code}')
            self.driver.send_content(XPATH="//input[@data-testid='ocfEnterTextTextInput']", content=code)
            self.log.info("点击下一步")
            self.driver.search_and_click(XPATH="//button[@data-testid='ocfEnterTextNextButton']", waiting_time=5.0)
        except:
            self.log.info("不需要邮箱验证码")
        try:
            div_element = self.driver.find_xpath(XPATH='//div[@class="css-175oi2r r-1awozwy r-16y2uox"]')
            self.log.info('存在弹窗提示，点击')
            div_element.find_element(By.TAG_NAME,'button').click()
            time.sleep(random.uniform(2,4))
        except:
            self.log.info('不存在弹窗提示')
       
        try:
            profile = self.driver.find_xpaths(XPATH='//a[@aria-label="Profile"]')
            if profile:
                profile = profile[-1].get_attribute("href")#主页链接
                self.log.info(f'找到主页链接：{profile}')
            else:
                self.log.error('未找到主页链接')
                return f'账号{account_id}登录失败'
                # return create_response(create_time=create_time,code=HTTPStatus.BAD_REQUEST,message='error',response=f'账号{account_id}登录失败')

            data = self.database.get_dict_data_sql(f"SELECT Account_id,Phone FROM accounts_info WHERE accounts_info.URL = '{profile}'")
            
            if data and data[0]['Account_id']!=account_id:
                self.log.info(f"输入账号为{account_id}与扫描账号{data[0]['Account_id']}不匹配，请检查后重新登录")
                sql = '''DELETE FROM accounts_info WHERE Account_id = %s;'''
                self.database.operation(sql,account_id)
                self.log.info(f"删除账号{account_id}")
                return f'输入账号手机号与扫描账号不匹配，已经删除新加入的账号，请检查后重新登录'
                # return create_response(create_time=create_time,code=HTTPStatus.BAD_REQUEST,message='error',response=f'输入账号手机号与扫描账号不匹配，已经删除新加入的账号，请检查后重新登录')
            # 更新cookies和账号的url,nickname
            new_cookies = json.dumps(self.driver.get_cookies(url="https://x.com/home"))
            self.log.info("获取新cookies")
            sql = '''UPDATE accounts_info SET Cookie = %s, Cookie_Status = %s, URL = %s, Platform = %s,Latest_login_time = %s WHERE Account_id = %s;'''
            self.database.operation(sql,(new_cookies,'在线',profile,'twitter',datetime.now(),account_id))
            time.sleep(3)
            self.log.info("更新数据库cookies成功")
            self.log.info(f'twitter账号{account_id}账号密码登录成功')
            await self.get_user_profile(account_id=account_id)
            # return create_response(create_time=create_time,code=HTTPStatus.OK,message='success',response=f'账号{account_id}登录成功')
            return f'账号{account_id}登录成功'
        except Exception as e:
            self.log.error("更新数据库cookies失败，原因：{}".format(e))
            # return create_response(create_time=create_time,code=HTTPStatus.BAD_REQUEST,message='error',response=f'账号{account_id}登录失败')
            return f'账号{account_id}登录失败'
    
        
    def get_verification_code(self,account_id):
        "获取验证码"
        try:
            sql = f"SELECT * FROM accounts_info where Account_id = '{account_id}'"
            result = self.database.get_dict_data_sql(sql)[0]
            self.log.info("从数据库中获取到的账号信息:{}".format(result))
            account = result['Account']
            password = result['Password']
            phone = result['Phone']
            self.log.info("进入推特")
            self.driver.get("https://twitter.com/?lang=zh")
            time.sleep(15)
            self.driver.search_and_click(XPATH="//a[@role = 'link' and @href = '/login']")
            self.log.info("点击登录")
            time.sleep(10)
            self.driver.send_content(XPATH="//input[@name = 'text']", content = account)
            self.log.info("输入账号")
            time.sleep(2)
            self.driver.search_and_click(XPATH="//span[contains(text(), '下一步')]", waiting_time=1.0)
            self.log.info("点击下一步")
            time.sleep(5)
            
            try: 
                self.driver.find_xpath(XPATH="//input[@data-testid='ocfEnterTextTextInput']")
                self.log.info("出现验证，需要输入手机号/邮箱号验证")
                self.driver.send_content(XPATH="//input[@data-testid='ocfEnterTextTextInput']", content=phone)
                self.log.info("点击下一步")
                self.driver.search_and_click(XPATH="//button[@data-testid='ocfEnterTextNextButton']", waiting_time=1.0)
            except:
                self.log.info("不需要输入手机号/邮箱号验证")
            self.driver.send_content(XPATH="//input[@type = 'password']", content = password)
            self.log.info("输入密码")
            time.sleep(2)
            self.log.info("点击登录")
            self.driver.search_and_click(XPATH="//span[contains(text(), '登录')]", waiting_time=5.0)
            
            try:
                self.driver.find_xpath(XPATH="//input[@inputmode='numeric']")
                # 截图返回到前端，用户输入2FAcode
                self.log.info(f'twitter账号{account_id}登录需要2FA验证码')
                os.makedirs(f'./QRcode/twitter/{account_id}/',exist_ok=True)
                image_path = f"./QRcode/twitter/{account_id}/verification.png"
                self.driver.find_xpath(XPATH='//div[@class="css-175oi2r r-1ny4l3l r-6koalj r-16y2uox r-14lw9ot r-1wbh5a2"]').screenshot(image_path)
                return image_path, f'需要代码生成器生成验证码，请输入账号{account}的2FAcode'
            except:
                self.log.info(f"twitter账号{account}不需要代码生成器生成验证码")
            # 检查是否有邮箱验证
            try:
                self.driver.find_xpath(XPATH='//span[contains(text(),"检查你的邮箱")]')
                self.log.info(f'twitter账号{account_id}需要邮箱验证')
                os.makedirs(f'./QRcode/twitter/{account_id}/',exist_ok=True)
                image_path = f"./QRcode/twitter/{account_id}/verification.png"
                self.driver.find_xpath(XPATH='//div[@class="css-175oi2r r-1ny4l3l r-6koalj r-16y2uox r-14lw9ot r-1wbh5a2"]').screenshot(image_path)
                return image_path, f'需要邮箱验证，请输入账号{account}邮箱接收到的验证码'
            except:
                self.log.info(f'twitter账号{account}不需要邮箱验证')
                
            try:
                self.driver.find_xpath(XPATH='//div[contains(text(),"Please verify your email address")]')
                self.log.info(f'twitter账号{account_id}需要验证邮箱地址，账号异常')
                os.makedirs(f'./QRcode/twitter/{account_id}/',exist_ok=True)
                image_path = f"./QRcode/twitter/{account_id}/verification.png"
                self.driver.find_xpath(XPATH='//div[@class="Section"]').screenshot(image_path)
                return image_path,f'账号{account}异常，无法完成登录，请更换新的账号'
            except:
                self.log.info(f'twitter账号{account}无异常，正常完成登录')
            return None,f'twitter账号{account}完成登录'
        except Exception as e:
            self.log.error("登录失败，原因：{}".format(e))
            return None, "登录失败，原因：{}".format(e)


    async def get_user_profile(self,account_id):
        "获取用户信息"
        try:
            create_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if 'https://x.com/' not in self.driver.driver.current_url:
                self.log.info(f'登录账号{account_id}')
                await self.login_by_cookies(account_id=account_id)
            sql = f"SELECT URL FROM accounts_info WHERE Account_id = '{account_id}'"
            url = self.database.get_dict_data_sql(sql)[0]['URL']
            if not url:
                url = self.driver.find_xpath(XPATH='//a[@aria-label="Profile"]').get_attribute("href")
                self.log.info(f'获取账号{account_id}的主页链接为：{url}')
                update_sql = '''UPDATE accounts_info SET URL = %s WHERE Account_id = %s;'''
                self.database.operation(update_sql,(url,account_id))
            self.driver.get(url)
            time.sleep(random.uniform(5,8))
            data = {"帐号昵称":None,"账号描述":None,"粉丝数":None,"关注数":None,"加入twitter的时间":None,"所在地":None,"帖子数":None,"头像链接":None}
            user_profile = self.get_user_pagehome(url)
            data["帐号昵称"] = user_profile["nickname"]
            data["账号描述"] = user_profile["user_description"]
            data["粉丝数"] = user_profile["followers_num"]
            data["关注数"] = user_profile["following_num"]
            data["加入twitter的时间"] = user_profile["user_join_date"]
            data["所在地"] = user_profile["user_location"]
            data["帖子数"] = user_profile["posts_num"]
            data["头像链接"] = user_profile["avatar_url"]
  
            self.log.info(f"获取的用户信息为：{data}")
            # 更新属性表
            result = self.database.get_dict_data_sql(sql=f"SELECT * FROM social_attributes WHERE Account_id = '{account_id}'")
            if not result:
                insert_sql = '''INSERT INTO `social_attributes`(`Account_id`,`Platform`) VALUES(%s,%s);'''
                self.database.operation(insert_sql,(account_id,'twitter'))
            sql = '''UPDATE social_attributes SET Account = %s, Fans_num = %s, Follows_num = %s, Post_num = %s,Location= %s,Account_description = %s,Joined_time = %s, Update_time=%s WHERE Account_id = %s;'''
            self.database.operation(sql,(user_profile['nickname'],user_profile['following_num'],user_profile['followers_num'],user_profile['posts_num'],user_profile["user_location"],user_profile["user_description"],user_profile["user_join_date"],datetime.now(),account_id))
            self.log.info(f'账号{account_id}的用户信息已保存到数据库')
            # 更新账号头像
            sql = '''UPDATE accounts_info SET Avatar_url = %s WHERE Account_id = %s;'''
            self.database.operation(sql,(user_profile["avatar_url"],account_id))
            self.log.info(f'账号{account_id}的头像链接已保存到数据库')
            # return 
            return create_response(create_time=create_time,code=HTTPStatus.OK,message='success',response=data)
        except Exception as e:        
            self.log.error(f'获取账号{account_id}用户信息失败:{e}')
            return create_response(create_time=create_time,code=HTTPStatus.BAD_REQUEST,message='error',response=f'账号{account_id}获取主页信息失败')
    
    
    def get_user_pagehome(self, url: str = None):
        "获取用户主页简介信息,url为用户主页链接"
        self.driver.get(url=url)
        time.sleep(random.uniform(10, 20))
        

        try:
            nickname = self.driver.search_and_get_content(xpath='//div[@data-testid="UserName"]/div[1]/div[1]/div[1]/div[1]/div[1]/div[1]/span[1]')#用户昵称
        except:
            nickname = url.split('/')[-1]
        try:
            user_description = self.driver.search_and_get_content(xpath='//div[@data-testid="UserDescription"]')#用户简介
        except:
            user_description = ""
        try:
            user_location = self.driver.search_and_get_content(xpath='//span[@data-testid="UserLocation"]')#用户地点
        except:
            user_location = ""
        try:
            user_join_date = self.driver.search_and_get_content(xpath='//span[@data-testid="UserJoinDate"]')#用户加入时间
        except:
            user_join_date = ""
        # try:
        #     #获取关注和粉丝数
        #     following = self.driver.find_xpath(XPATH='//a[contains(@href, "following")]').text
        #     following_num = following.replace("Following","").strip()
        #     followers = self.driver.find_xpath(XPATH='//a[contains(@href, "followers")]').text
        #     followers_num = followers.replace("Followers","").strip()
        # except:
        #     following_num = ""
        #     followers_num = ""
        # try:
        #     posts_num = self.driver.search_and_get_content(xpath='//div[@class="css-146c3p1 r-dnmrzs r-1udh08x r-1udbk01 r-3s2u2q r-bcqeeo r-1ttztb7 r-qvutc0 r-37j5jr r-n6v787 r-1cwl3u0 r-16dba41" and contains(text(),"posts")]').replace("posts","").strip()#用户发帖数
        # except:
        #     posts_num = ""
       
        # 获取关注数、粉丝数和贴文数的具体值
        try:
            script_elem = self.driver.driver.find_element(By.CSS_SELECTOR, 'script[type="application/ld+json"][data-testid="UserProfileSchema-test"]')
            # 获取JSON字符串
            json_text = script_elem.get_attribute("innerHTML")
            data = json.loads(json_text)
            stats = data["mainEntity"]["interactionStatistic"]
            # def get_count(name):
            #     for item in stats:
            #         if item.get("name") == name:
            #             return item.get("userInteractionCount", 0)
            #     return 0
            # following_num = get_count("Follows")
            # followers_num = get_count("Friends") 
            # posts_num = get_count("Tweets")  
            followers_num = str(stats[0].get("userInteractionCount", 0))
            following_num = str(stats[1].get("userInteractionCount", 0))
            posts_num = str(stats[2].get("userInteractionCount", 0))

        except:
            following_num = ""
            followers_num = ""
            posts_num = ""


        try:
            self.driver.get(url=f'{url}/photo')
            time.sleep(random.uniform(10, 20))
            avatar_url = self.driver.find_xpath(XPATH='//img[@alt="Image" and @class="css-9pa8cd"]').get_attribute('src')
        except:
            avatar_url = None
        return {'nickname':nickname,'url':url,'user_description':user_description,'user_location':user_location,'user_join_date':user_join_date,'following_num':following_num,'followers_num':followers_num,'posts_num':posts_num,"avatar_url":avatar_url}
  
     
    async def posts(self,account_id,content,file_paths:list=None):
        '''发帖'''
        try:
            create_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if 'https://x.com/' not in self.driver.driver.current_url:
                await self.login_by_cookies(account_id=account_id)
            

            # 消除BMP字符
            content = ''.join(c for c in content if ord(c) <= 0xFFFF)
            note_type = '原创'
            self.driver.get(url='https://twitter.com/home')
            time.sleep(random.uniform(3,5))
            self.log.info("点击文本框")
            self.driver.search_and_click(XPATH='//div[@data-testid="tweetTextarea_0_label"]',waiting_time=1.0) # 点一下激活输入框
            self.driver.send_content(XPATH='//div[@class="public-DraftStyleDefault-block public-DraftStyleDefault-ltr"]',content = content)
            time.sleep(random.uniform(5,8))
            if file_paths:
                self.log.info("上传图片/视频")
                self.driver.send_content(XPATH="//input[@data-testid = 'fileInput']", content = '\n'.join(file_paths))#上传图片/视频）
                time.sleep(random.uniform(5,10))
            action_time = datetime.now()
            self.log.info(f'点击发帖按钮')
            self.driver.search_and_click(XPATH="//button[@role = 'button' and @data-testid='tweetButtonInline']")#点击发帖
            self.log.info("twitter帖子发布成功")
            try:
                self.driver.find_xpath(XPATH='//div[@class="css-175oi2r r-1awozwy r-16y2uox"]')
                self.log.info(f'存在提示框，点击 我知道了')
                self.driver.search_and_click(XPATH='//button[contains(@class,"css-175oi2r r-sdzlij r-1phboty r-rs99b7 r-lrvibr r-1mnahxq")]',waiting_time=2.0)
            except:
                self.log.info(f'不存在提示框')
            time.sleep(random.uniform(5,10))
            content_url = self.get_content_url(account_id=account_id)
            self.log.info(f'获取发布成功帖子的链接:{content_url}')
            # 添加到互动表，
            if content_url:
                # 添加到交互表中
                post_result = str([{content_url :content}])
                insert_sql = '''INSERT INTO `twitter_interaction`(`Account_id`,`Platform`,`Content`,`Type`,`Action`,`URL`,`Interaction_time`,`Result_list`,`Update_time`) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s);'''
                self.database.operation(insert_sql,(account_id,'twitter',content,note_type,'发帖',post_result,action_time,None,datetime.now()))
                self.log.info(f'发帖 已更新到数据库twitter互动表')
                return create_response(create_time=create_time,code=HTTPStatus.OK,message='success',response=f'账号{account_id}发布成功：{content_url}')  
            else:
                self.log.error(f'账号{account_id}twitter内容发布失败，未获得有效作品链接') 
                return create_response(create_time=create_time,code=HTTPStatus.BAD_REQUEST,message='error',response=f'账号{account_id}发布失败') 
        except Exception as e:
            self.log.error(f'账号{account_id}twitter内容发布失败，原因是：{e}')
            return create_response(create_time=create_time,code=HTTPStatus.BAD_REQUEST,message='error',response=f'账号{account_id}发布失败') 
    
     
    def get_content_url(self,account_id):
        '''获取账号account_id刚发布的帖子链接'''
        try:
            search_sql = f"SELECT * FROM accounts_info WHERE accounts_info.Account_id = {account_id}"
            result = self.database.get_dict_data_sql(search_sql)
            account_url = result[0]['URL']
            self.log.info(f'进入twitter账号{account_id}主页:{account_url}')
            self.driver.get(url = account_url )
            time.sleep(5)
            # 第一个twitter帖子
            first_article_element = self.driver.find_xpath(XPATH='//article[@data-testid="tweet"]')
            self.driver.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", first_article_element)
            time.sleep(random.uniform(1,3))
            a_element = first_article_element.find_element(By.XPATH,'.//div[@class="css-175oi2r r-18u37iz r-1q142lx"]')
            content_url = a_element.find_element(By.TAG_NAME,'a').get_attribute("href")
            self.log.info(f'获取账号{account_id}的帖子链接成功，链接是：{content_url}')
            return content_url     
        except Exception as e:
            self.log.error(f'获取twitter账号{account_id}发布的帖子链接失败，原因是：{e}')
            return None
     
     
    async def get_one_content(self,url:str=None):
        '''获取某贴文的具体信息'''
        data = {"nickname":'',"user_url":'',"note_url":'',"note_form":'',"note_type":'',"post_time_ip":'',"title":'', "content":'', "transmits":'',"views":'',"comments":'',"bookmarks":'',"likes":'',"images_url":[]}
        
        try:
            if url:
                # data["note_url"] = url
                self.log.info(f'进入网址：{url}获取笔记具体内容')
                self.driver.open_new_tab(url=url)
                time.sleep(random.uniform(5,10))
                self.driver.swith_to_new_window(-1)
                time.sleep(2)
            images_url = [] 
            data["note_url"] = self.driver.driver.current_url
            html = self.driver.driver.page_source 
            soup = BeautifulSoup(html, "lxml")  # html.parser 
            href = data["note_url"] .replace('https://x.com','')
            # 使用正则
            STATUS_RE = re.compile(r'^(/[^/]+/status/\d+)(?:[/?#].*)?$')
            m = STATUS_RE.match(href)
            href =  m.group(1) if m else href
            # href = href[:-1] if href[-1] == '/' else href
            a_tag = soup.find('a', href=re.compile(href))
            article = a_tag.find_parent('article')
            # 查找用户昵称
            data["nickname"] = article.find('div',class_="css-175oi2r r-1awozwy r-18u37iz r-1wbh5a2 r-dnmrzs").get_text().strip()
            data["user_url"] = 'https://x.com/' + data["note_url"].split('/')[3] 
            trans_tweets = article.find_all('div',attrs={"data-testid": "tweetText"})
            if len(trans_tweets) == 1:
                data["note_type"] = '原创'
                data["content"] = trans_tweets[0].get_text().replace('\n','')
            elif len(trans_tweets) >1 :
                data["note_type"] = '转发'
                data["content"] = trans_tweets[0].get_text().replace('\n','')
            else:
                data["note_type"] = '原创'
                data["content"] = ''
            images = article.find_all("img",attrs={"alt": "Image"})
            video = article.find_all('div',class_="css-175oi2r r-1p0dtai r-1d2f490 r-u8s1d r-zchlnj r-ipm5af r-1loqt21")
            if images:
                data["note_form"] = '图文'
                for image in images:
                    images_url.append(image.get("src"))
            elif video:
                data["note_form"] = '视频'
            else:
                data["note_form"] = '文字'
            len(article.find_all('time'))
            if data['note_type'] == '原创':
                data["post_time_ip"] = article.find('time').get("datetime") if article.find('time') else ''
            elif data['note_type'] == '转发':
                data["post_time_ip"] = article.find_all('time')[-1].get("datetime") if article.find('time') else ''
            text = self.driver.find_xpath(XPATH='//div[contains(@class,"css-175oi2r r-1kbdv8c r-18u37iz r-1oszu61")]').get_attribute("aria-label")  # 贴文的数据量
            results = {"replies": 0,"reposts": 0,"likes": 0,"bookmarks": 0,"views": 0}
            # 单数变成复数
            text = text.replace('like','likes').replace('reply','replies').replace('repost','reposts').replace('bookmark','bookmarks').replace('view','views')
            matches = re.findall(r'(\d[\d,]*)\s+(replies|reposts|likes|bookmarks|views)', text)
            for num, key in matches:
                num = num.replace(",", "")
                results[key] = num 
            data["comments"] =results["replies"]
            data["transmits"] = results["reposts"]
            data["likes"] = results["likes"]
            data["views"] = results["views"]
            data["bookmarks"] = results["bookmarks"]
            data["images_url"] = images_url

            if url:
               await self.close_now_windows()
            return data
        
        except Exception as e:
            self.log.error(f'爬取twitter内容失败，原因是：{e}')
            if url:
               await self.close_now_windows()
            return {}  


    async def likes(self,account_id,url):
        '''点赞某贴文'''
        '''
        参数：
            -account_id:账号id
            -url：指定帖子/视频的链接
        返回：None
        '''
        try:
            create_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if 'https://x.com/' not in self.driver.driver.current_url:
                await self.login_by_cookies(account_id=account_id)
            if self.driver.driver.current_url != url:
                self.log.info(f'进入帖子{url}')
                self.driver.get(url)
                time.sleep(random.uniform(8,15))
            data = await self.get_one_content()
            
            self.log.info('点击点赞按钮')
            action_time = datetime.now()
            article = self.driver.find_xpath(XPATH='//article[@role="article" and following-sibling::div[@data-testid="inline_reply_offscreen"]]')
            try:
                likes_element = article.find_element(By.XPATH,'.//button[@data-testid="like"]')
                self.driver.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", likes_element)
                time.sleep(random.uniform(2,4))
                likes_element.click()
                time.sleep(random.uniform(2,4))
            except:
                try:
                    article.find_element(By.XPATH,'.//button[@data-testid="unlike"]')
                    self.log.info(f'账号{account_id}已经点赞过帖子{url}')
                    return create_response(create_time=create_time,code=HTTPStatus.OK,message='success',response=f'账号{account_id}点赞成功')
                except:
                    raise Exception
            self.log.info("twitter点赞成功")
            time.sleep(random.uniform(2,4))
            # 添加到互动表，
            now_time = datetime.now()
            insert_sql = '''INSERT INTO `twitter_interaction`(`Account_id`,`Platform`,`Content`,`Type`,`Action`,`URL`,`Interaction_time`,`Result_list`,`Update_time`) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s);'''
            self.database.operation(insert_sql,(account_id,'twitter',data['content'],data["note_type"],'点赞',url,action_time,None,now_time))
            self.log.info('点赞 已更新到数据库twitter互动表')
            # 添加到曝光表中
            # 添加到曝光表中
            insert_sql = '''INSERT INTO `twitter_records`(`Account_id`,`Platform`,`URL`,`Source_account`,`Content`,`Likes_Num`,`Transmits_Num`,`Views_Num`,`Bookmarks_Num`,`Comments_Num`,`Published_Time_IP`,`Type`,`Form`,`Images_URL`,`Update_time`) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s);'''
            self.database.operation(insert_sql,(account_id,'twitter',data["note_url"],data["nickname"],data["content"],data["likes"],data["transmits"],data["views"],data["bookmarks"],data["comments"],data["post_time_ip"],data["note_type"],data["note_form"],str(data["images_url"]),datetime.now()))
            self.log.info('已更新twitter内容曝光表')
            
            return create_response(create_time=create_time,code=HTTPStatus.OK,message='success',response=f'账号{account_id}点赞成功')
        except Exception as e:
            self.log.error(f"账号{account_id}点赞失败，原因：{e}")
            return create_response(create_time=create_time,code=HTTPStatus.BAD_REQUEST,message='error',response=f'账号{account_id}点赞失败')
    
    
    async def bookmarks(self,account_id,url):
        '''bookmarks某贴文'''
        '''
        参数：
            -account_id:账号id
            -url：指定帖子/视频的链接
        返回：None
        '''
        try:
            create_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if 'https://x.com/' not in self.driver.driver.current_url:
                await self.login_by_cookies(account_id=account_id)

            if self.driver.driver.current_url != url:
                self.log.info(f'进入帖子{url}')
                self.driver.get(url)
                time.sleep(random.uniform(5,10))

            data = await self.get_one_content()
            self.log.info('点击bookmarks按钮')
            action_time = datetime.now()
            article = self.driver.find_xpath(XPATH='//article[@role="article" and following-sibling::div[@data-testid="inline_reply_offscreen"]]')
            try:
                bookmarks_element = article.find_element(By.XPATH,'.//button[@data-testid="bookmark"]')
                self.driver.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", bookmarks_element)
                time.sleep(random.uniform(2,4))
                bookmarks_element.click()
                time.sleep(random.uniform(2,4))
            except:
                try:
                    article.find_element(By.XPATH,'.//button[@data-testid="removeBookmark"]')
                    self.log.info(f'账号{account_id}已经点赞过帖子{url}')
                    return create_response(create_time=create_time,code=HTTPStatus.OK,message='success',response=f'账号{account_id}bookmark成功')
                except:
                    raise Exception
            self.log.info("twitter bookmark成功")
            time.sleep(random.uniform(2,4))
            # 添加到互动表，
            now_time = datetime.now()
            insert_sql = '''INSERT INTO `twitter_interaction`(`Account_id`,`Platform`,`Content`,`Type`,`Action`,`URL`,`Interaction_time`,`Result_list`,`Update_time`) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s);'''
            self.database.operation(insert_sql,(account_id,'twitter',data['content'],data["note_type"],'bookmark',url,action_time,None,now_time))
            self.log.info('bookmark 已更新到数据库twitter互动表')
            # 添加到曝光表中
            # 添加到曝光表中
            insert_sql = '''INSERT INTO `twitter_records`(`Account_id`,`Platform`,`URL`,`Source_account`,`Content`,`Likes_Num`,`Transmits_Num`,`Views_Num`,`Bookmarks_Num`,`Comments_Num`,`Published_Time_IP`,`Type`,`Form`,`Images_URL`,`Update_time`) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s);'''
            self.database.operation(insert_sql,(account_id,'twitter',data["note_url"],data["nickname"],data["content"],data["likes"],data["transmits"],data["views"],data["bookmarks"],data["comments"],data["post_time_ip"],data["note_type"],data["note_form"],str(data["images_url"]),datetime.now()))
            self.log.info('已更新twitter内容曝光表')
            
            return create_response(create_time=create_time,code=HTTPStatus.OK,message='success',response=f'账号{account_id}bookmark成功')
        except Exception as e:
            self.log.error(f"账号{account_id}bookmark失败，原因：{e}")
            return create_response(create_time=create_time,code=HTTPStatus.BAD_REQUEST,message='error',response=f'账号{account_id}bookmark失败')
        
        
    async def comments(self,account_id,url,content,file_paths:list=None):
        '''
        评论指定帖子

        参数：
            -account_id:账号id
            -url：指定帖子链接
            -content：评论内容
        返回：None
        ''' 
        try:
            create_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if 'https://x.com/' not in self.driver.driver.current_url:
                await self.login_by_cookies(account_id=account_id)

            if self.driver.driver.current_url != url:
                self.log.info(f'进入帖子{url}')
                self.driver.get(url)
                time.sleep(random.uniform(15,30))
            # 消除BMP字符
            content = ''.join(c for c in content if ord(c) <= 0xFFFF)
            data = await self.get_one_content()
            action_time = datetime.now()
            time.sleep(random.uniform(2,4))
            comments_element = self.driver.find_xpath(XPATH='//div[@data-testid="tweetTextarea_0RichTextInputContainer"]')
            self.driver.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", comments_element)
            time.sleep(random.uniform(0.5,1.5))
            # self.log.info("点击评论输入框")
            # self.driver.search_and_click(XPATH='//div[@data-testid="tweetTextarea_0RichTextInputContainer"]',waiting_time=1.0)
            comments_element.click()
            time.sleep(random.uniform(2,4))
            self.log.info("输入评论内容")
            self.driver.send_content(XPATH='//div[@class="public-DraftStyleDefault-block public-DraftStyleDefault-ltr"]',content = content)
            time.sleep(random.uniform(3,5))
            if file_paths:
                self.log.info("上传图片/视频")
                self.driver.send_content(XPATH="//input[@data-testid = 'fileInput']", content = '\n'.join(file_paths))#上传图片/视频）
                time.sleep(random.uniform(5,10))

            self.log.info('点击发送按钮')
            self.driver.search_and_click(XPATH="//button[@role = 'button' and @data-testid='tweetButtonInline']",waiting_time=5.0)
            self.log.info("twitter评论成功")
            # 可能会出现弹窗
            try:
                self.driver.search_and_click(XPATH="//button[.//span[contains(text(),'Maybe later')]]",waiting_time=random.uniform(5,15))
            except:
                pass

            # 获取链接内容
            select_sql = f'''SELECT * FROM accounts_info WHERE account_id = {account_id}'''
            nickname  = self.database.get_dict_data_sql(select_sql)[0]['Account']
            content_url = self.driver.find_xpath(XPATH=f'.//a[contains(@class,"css-146c3p1 r-bcqeeo r-1ttztb7 r-qvutc0 ") and contains(@href,"/{nickname}/status/")]').get_attribute('href')
            
            self.log.info(f'评论成功，评论内容的链接是：{content_url}')
            time.sleep(random.uniform(5,10))
            # 添加到互动表，将评论内容的链接作为results_list
            now_time = datetime.now()
            comment_result = str([{content_url :content}])
            insert_sql = '''INSERT INTO `twitter_interaction`(`Account_id`,`Platform`,`Content`,`Type`,`Action`,`URL`,`Interaction_time`,`Result_list`,`Update_time`) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s);'''
            self.database.operation(insert_sql,(account_id,'twitter',data["content"],data["note_type"],'评论',url,action_time,comment_result,now_time))
            self.log.info('评论 已更新到数据库twitter互动表')  
           
            # 添加到曝光表中
            transmit_form  =  '文字' if not file_paths  else '图文'
            account_name =  self.database.get_dict_data_sql(sql=f'''SELECT Account FROM accounts_info WHERE Account_id={account_id};''')[0]['Account']
            insert_sql = '''INSERT INTO `twitter_records`(`Account_id`,`Platform`,`URL`,`Source_account`,`Content`,`Likes_Num`,`Transmits_Num`,`Views_Num`,`Bookmarks_Num`,`Comments_Num`,`Published_Time_IP`,`Type`,`Form`,`Images_URL`,`Update_time`) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s);'''
            self.database.operation(insert_sql,(account_id,'twitter',content_url,account_name,content,'0','0','0','0','0',action_time,'评论',transmit_form,str(file_paths),datetime.now()))
            self.log.info('已更新twitter内容曝光表')            
            
            return create_response(create_time=create_time,code=HTTPStatus.OK,message='success',response=f'账号{account_id}评论成功：{content_url}')
        except Exception as e:
            self.log.error(f"账号{account_id}评论失败，原因：{e}")
            return create_response(create_time=create_time,code=HTTPStatus.BAD_REQUEST,message='error',response=f'账号{account_id}评论失败')

  
     
     
    async def transmits(self,account_id,url,content=None,file_paths:list=None):
        '''
        转发指定帖子

        参数：
            -account_id:账号id
            -url：指定帖子链接
            -content：转内容
        返回：None
        ''' 
        try:
            
            create_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if 'https://x.com/' not in self.driver.driver.current_url:
                await self.login_by_cookies(account_id=account_id)
            if self.driver.driver.current_url != url:
                self.log.info(f'进入帖子{url}')
                self.driver.get(url)
                time.sleep(random.uniform(8,15))

            data = await self.get_one_content()
            action_time = datetime.now()   
            time.sleep(random.uniform(2,4))
            article = self.driver.find_xpath(XPATH='//article[@role="article" and following-sibling::div[@data-testid="inline_reply_offscreen"]]')

            if not content:  # 快转
                try:
                    transmits_element = article.find_element(By.XPATH,'.//button[@data-testid="retweet"]')
                    self.driver.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", transmits_element)
                    time.sleep(random.uniform(2,4))
                    transmits_element.click()
                    time.sleep(random.uniform(2,5))
                except:
                    try:
                        article.find_element(By.XPATH,'.//button[@data-testid="unretweet"]')
                        self.log.info(f'账号{account_id}已经repost过帖子{url}')
                        return create_response(create_time=create_time,code=HTTPStatus.OK,message='success',response=f'账号{account_id}转发成功')
                    except:
                        raise Exception
                self.log.info("点击repost直接转发按钮")
                self.driver.search_and_click(XPATH='//div[@data-testid="retweetConfirm"]',waiting_time=2.0)
                self.log.info("twitter快转成功")
                time.sleep(random.uniform(2,4))
                # 添加到互动表，
                now_time = datetime.now()
                insert_sql = '''INSERT INTO `twitter_interaction`(`Account_id`,`Platform`,`Content`,`Type`,`Action`,`URL`,`Interaction_time`,`Result_list`,`Update_time`) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s);''' 
                self.database.operation(insert_sql,(account_id,'twitter',data['content'],data["note_type"],"快转",url,action_time,None,now_time))
                self.log.info('快转 已更新到数据库twitter互动表')
                
                # 添加到曝光表中
                insert_sql = '''INSERT INTO `twitter_records`(`Account_id`,`Platform`,`URL`,`Source_account`,`Content`,`Likes_Num`,`Transmits_Num`,`Views_Num`,`Bookmarks_Num`,`Comments_Num`,`Published_Time_IP`,`Type`,`Form`,`Images_URL`,`Update_time`) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s);'''
                self.database.operation(insert_sql,(account_id,'twitter',data["note_url"],data["nickname"],data["content"],data["likes"],data["transmits"],data["views"],data["bookmarks"],data["comments"],data["post_time_ip"],data["note_type"],data["note_form"],str(data["images_url"]),datetime.now()))
                self.log.info('已更新twitter内容曝光表')
                return create_response(create_time=create_time,code=HTTPStatus.OK,message='success',response=f'账号{account_id}快转成功')
            
            else:  # 带文转发
                self.log.info("点击转发")
                try:
                    transmits_element = article.find_element(By.XPATH,'.//button[@data-testid="retweet"]')
                    self.driver.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", transmits_element)
                    time.sleep(random.uniform(0.5,2))
                    transmits_element.click()
                    time.sleep(random.uniform(2,5))
                except:
                    try:
                        article.find_element(By.XPATH,'.//button[@data-testid="unretweet"]').click()
                        time.sleep(random.uniform(2,4))
                    except:
                        raise Exception
                self.driver.search_and_click(XPATH='//a[@role="menuitem"]',waiting_time=1.0)
                self.log.info("点击quote转发按钮")
                self.driver.send_content(XPATH='//div[@class="public-DraftStyleDefault-block public-DraftStyleDefault-ltr"]/span[1]',content=content)
                if file_paths:
                    self.log.info("上传图片/视频")
                    self.driver.send_content(XPATH="//input[@data-testid = 'fileInput']", content = '\n'.join(file_paths))#上传图片/视频）
                    time.sleep(random.uniform(5,10))
                self.log.info('转发中，内容：{}'.format(content))
                time.sleep(random.uniform(2,4))
                try:
                    self.driver.search_and_click(XPATH='//div[@data-testid="typeaheadResult"]',waiting_time=random.uniform(2,4))
                except:
                    pass
                self.driver.search_and_click(XPATH='//button[@data-testid="tweetButton"]',waiting_time=random.uniform(2,4))
                self.log.info("twitter转发成功")
                # 获取转发内容的链接
                content_url = self.get_content_url(account_id=account_id)
                self.log.info(f'转发成功，转发内容的链接是：{content_url}')
                # 添加到互动表，
                if content_url:
                    # 添加到交互表中
                    # transmit_result = content_url +':'+content
                    transmit_result = str([{content_url :content}])
                    insert_sql = '''INSERT INTO `twitter_interaction`(`Account_id`,`Platform`,`Content`,`Type`,`Action`,`URL`,`Interaction_time`,`Result_list`,`Update_time`) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s);'''
                    self.database.operation(insert_sql,(account_id,'twitter',data['content'],data["note_type"],'转发',url,action_time,transmit_result,datetime.now()))
                    self.log.info(f'转发 已更新到数据库twitter互动表')
                    
                    # 添加到曝光表中
                    transmit_form  =  '文字' if len(file_paths) == 0 else '图文'
                    account_name =  self.database.get_dict_data_sql(sql=f'''SELECT Account FROM accounts_info WHERE Account_id={account_id};''')[0]['Account']
                    insert_sql = '''INSERT INTO `twitter_records`(`Account_id`,`Platform`,`URL`,`Source_account`,`Content`,`Likes_Num`,`Transmits_Num`,`Views_Num`,`Bookmarks_Num`,`Comments_Num`,`Published_Time_IP`,`Type`,`Form`,`Images_URL`,`Update_time`) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s);'''
                    self.database.operation(insert_sql,(account_id,'twitter',content_url,account_name,content,'0','0','0','0','0',action_time,'转发',transmit_form,str(file_paths),datetime.now()))
                    self.log.info('已更新twitter内容曝光表')
                    
                    return create_response(create_time=create_time,code=HTTPStatus.OK,message='success',response=f'账号{account_id}转发成功：{content_url}')  
                else:
                    raise Exception
        except Exception as e:
            self.log.error(f"账号{account_id}转发失败，原因：{e}")
            return create_response(create_time=create_time,code=HTTPStatus.BAD_REQUEST,message='error',response=f'账号{account_id}转发失败')

     

    async def follows(self,account_id,url):
        '''
        参数：
            -account_id:账号id
            -url：用户主页链接/帖子链接
        返回：None
        '''
        try:
            create_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if 'https://x.com/' not in self.driver.driver.current_url:
                await self.login_by_cookies(account_id=account_id)

            if self.driver.driver.current_url != url:
                self.log.info(f'进入指定帖子/用户主页链接{url}')
                self.driver.get(url=url)
                time.sleep(random.uniform(8,15))

            self.log.info('点击关注按钮')
            action_time = datetime.now()
            if "/status/" in url:
                self.log.info(f'链接{url}是帖子链接')
                data = await self.get_one_content()
                note_type = data["note_type"]
                self.log.info(f'点击...按钮')
                self.driver.search_and_click(XPATH='//button[@aria-label="More" and @aria-haspopup="menu"]',waiting_time=random.uniform(2,4))
                text = self.driver.find_xpath(XPATH='//div[@data-testid="Dropdown"]/div[1]/div[2]/div[1]/span[1]').text
                # 将帖子信息添加到曝光表中
                insert_sql = '''INSERT INTO `twitter_records`(`Account_id`,`Platform`,`URL`,`Source_account`,`Content`,`Likes_Num`,`Transmits_Num`,`Views_Num`,`Bookmarks_Num`,`Comments_Num`,`Published_Time_IP`,`Type`,`Form`,`Images_URL`,`Update_time`) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s);'''
                self.database.operation(insert_sql,(account_id,'twitter',data["note_url"],data["nickname"],data["content"],data["likes"],data["transmits"],data["views"],data["bookmarks"],data["comments"],data["post_time_ip"],data["note_type"],data["note_form"],str(data["images_url"]),datetime.now()))
                self.log.info('已更新twitter内容曝光表')
                if 'Follow' in text:
                    self.log.info(f'暂未关注该作者，点击关注')
                    self.driver.search_and_click(XPATH='//div[@data-testid="Dropdown"]/div[1]',waiting_time=random.uniform(2,4))
                elif 'Unfollow' in text:
                    self.log.info(f'已经关注过该作者，无需重复关注')
                    return create_response(create_time=create_time,code=HTTPStatus.OK,message='success',response=f'账号{account_id}已关注过该作者，无需重复关注')
            else:
                self.log.info(f'链接{url}是作者主页链接')
                note_type = None
                try:
                    follow_button = self.driver.find_xpath(XPATH='//button[contains(@aria-label,"Follow")]')
                    self.log.info(f'暂未关注该作者，点击关注')
                    follow_button.click()
                    time.sleep(random.uniform(2,4))
                except:
                    try:
                        self.driver.find_xpath(XPATH='//button[contains(@aria-label,"Unfollow")]')
                        self.log.info(f'已经关注过该作者，无需重复关注')
                        return create_response(create_time=create_time,code=HTTPStatus.OK,message='success',response=f'账号{account_id}已关注过该作者，无需重复关注')
                    except:
                        raise Exception
            self.log.info('twitter关注成功')
            time.sleep(random.uniform(2,4))
            # 添加到互动表，
            now_time = datetime.now()
            insert_sql = '''INSERT INTO `twitter_interaction`(`Account_id`,`Platform`,`Content`,`Type`,`Action`,`URL`,`Interaction_time`,`Result_list`,`Update_time`) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s);'''
            self.database.operation(insert_sql,(account_id,'twitter',None,note_type,'关注',url,action_time,None,now_time))
            self.log.info('关注 已更新到数据库twitter互动表')
            return create_response(create_time=create_time,code=HTTPStatus.OK,message='success',response=f'账号{account_id}关注成功')
        except Exception as e:
            self.log.error(f"账号{account_id}关注失败:{e}")
            return create_response(create_time=create_time,code=HTTPStatus.BAD_REQUEST,message='error',response=f'账号{account_id}关注失败')


    async def notfollows(self,account_id,url):
        ''' 取消关注
        参数：
            -account_id:账号id
            -url：用户主页链接/帖子链接
        返回：None
        '''
        try:
            create_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if 'https://x.com/' not in self.driver.driver.current_url:
                await self.login_by_cookies(account_id=account_id)
            self.log.info(f'进入指定帖子/用户主页链接{url}')
            self.driver.get(url=url)
            time.sleep(random.uniform(8,15))
            self.log.info('点击取消关注按钮')
            action_time = datetime.now()
            if "/status/" in url:
                self.log.info(f'链接{url}是帖子链接')
                data = await self.get_one_content()
                note_type = data["note_type"]
                self.log.info(f'点击...按钮')
                self.driver.search_and_click(XPATH='//button[@aria-label="More" and @aria-haspopup="menu"]',waiting_time=random.uniform(2,4))
                text = self.driver.find_xpath(XPATH='//div[@data-testid="Dropdown"]/div[1]/div[2]/div[1]/span[1]').text
                # 将帖子信息添加到曝光表中
                insert_sql = '''INSERT INTO `twitter_records`(`Account_id`,`Platform`,`URL`,`Source_account`,`Content`,`Likes_Num`,`Transmits_Num`,`Views_Num`,`Bookmarks_Num`,`Comments_Num`,`Published_Time_IP`,`Type`,`Form`,`Images_URL`,`Update_time`) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s);'''
                self.database.operation(insert_sql,(account_id,'twitter',data["note_url"],data["nickname"],data["content"],data["likes"],data["transmits"],data["views"],data["bookmarks"],data["comments"],data["post_time_ip"],data["note_type"],data["note_form"],str(data["images_url"]),datetime.now()))
                self.log.info('已更新twitter内容曝光表')
                if 'Follow' in text:
                    self.log.info(f'暂未关注过该作者，无需点击取消关注')
                    return create_response(create_time=create_time,code=HTTPStatus.OK,message='success',response=f'账号{account_id}暂未关注该作者，无需点击取消关注')
                elif 'Unfollow' in text:
                    self.log.info(f'关注该作者，点击取消关注')
                    self.driver.search_and_click(XPATH='//div[@data-testid="Dropdown"]/div[1]',waiting_time=random.uniform(2,4))       
            else:
                self.log.info(f'链接{url}是作者主页链接')
                note_type = None
                try:
                    follow_button = self.driver.find_xpath(XPATH='//button[contains(@aria-label,"Unfollow")]')
                    self.log.info(f'关注该作者，点击取消关注')
                    follow_button.click()
                    time.sleep(random.uniform(1,3))
                    self.driver.search_and_click(XPATH='//div[@data-testid="Dropdown"]/div[1]',waiting_time=random.uniform(2,4))     
                except:
                    try:
                        self.driver.find_xpath(XPATH='//button[contains(@aria-label,"Follow")]')
                        self.log.info(f'暂未关注过该作者，无需点击取消关注')
                        return create_response(create_time=create_time,code=HTTPStatus.OK,message='success',response=f'账号{account_id}暂未关注该作者，无需点击取消关注')
                    except:
                        raise Exception
            self.log.info('twitter取消关注成功')
            time.sleep(random.uniform(2,4))
            # 添加到互动表，
            now_time = datetime.now()
            insert_sql = '''INSERT INTO `twitter_interaction`(`Account_id`,`Platform`,`Content`,`Type`,`Action`,`URL`,`Interaction_time`,`Result_list`,`Update_time`) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s);'''
            self.database.operation(insert_sql,(account_id,'twitter',None,note_type,'取消关注',url,action_time,None,now_time))
            self.log.info('取消关注 已更新到数据库twitter互动表')
            return create_response(create_time=create_time,code=HTTPStatus.OK,message='success',response=f'账号{account_id}取消关注成功')
        except Exception as e:
            self.log.error(f"账号{account_id}取消关注失败:{e}")
            return create_response(create_time=create_time,code=HTTPStatus.BAD_REQUEST,message='error',response=f'账号{account_id}取消关注失败')
     
     
     
    async def get_hot_words(self,account_id):
        "获取热搜词"
        try:
            create_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if 'https://x.com/' not in self.driver.driver.current_url:
                await self.login_by_cookies(account_id=account_id)
            action_time = datetime.now()
            self.driver.get(url="https://x.com/explore/tabs/trending")
            self.log.info("进入热榜页面")
            time.sleep(random.uniform(5,10))
            hotwords_list = self.driver.search_and_get_all_content(xpath='//div[@class="css-146c3p1 r-bcqeeo r-1ttztb7 r-qvutc0 r-37j5jr r-a023e6 r-rjixqe r-b88u0q r-1bymd8e"]')
            self.log.info(f'账号{account_id}获取到的twitter热搜词共：{len(hotwords_list)}个,分别是“{hotwords_list}')        
            # 存到交互表中
            now_time = datetime.now()
            insert_sql = '''INSERT INTO `twitter_interaction`(`Account_id`,`Platform`,`Content`,`Type`,`Action`,`URL`,`Interaction_time`,`Result_list`,`Update_time`) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s);'''
            self.database.operation(insert_sql,(account_id,'twitter',str(hotwords_list),None,'获取热搜',None,action_time,None,now_time))
            self.log.info('获取热搜 已更新到数据库twitter互动表')
            return create_response(create_time=create_time,code=HTTPStatus.OK,message='success',response=hotwords_list) 
        except Exception as e:
            self.log.error(f'账号{account_id}获取热搜词条失败，原因：{e}')
            return create_response(create_time=create_time,code=HTTPStatus.BAD_REQUEST,message='error',response=f'账号{account_id}获取twitter热搜词失败')

     
    async def get_keyword_contents(self,account_id,keyword,num=10,time_limit:int=None):
        '''爬取某个关键字的所有内容'''
        create_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            
            if 'https://x.com' not in self.driver.driver.current_url:
                await self.login_by_cookies(account_id=account_id)
            url = f"https://twitter.com/search?q={keyword}&src=typed_query&f=live"  # 选择 Latest
            
            since_time = None
            if time_limit is not None:
                end_time=convert_time_us(datetime.now()) # 获取当前中国时间并转化为美国时间
                since_time = end_time - timedelta(days=time_limit)
                self.log.info(f"开始获取从 {since_time} 到现在 {end_time} 的关键字检索推文")

            all_content = []
            self.driver.get(url=url)
            self.log.info("进入页面")
            time.sleep(random.uniform(8,12))
            select_num = 0
            action_time = datetime.now()
            self.log.info(f'开始获取关于“{keyword}”的相关twitter内容')
            article = self.driver.find_xpath(XPATH='//div[@class="css-175oi2r" and @data-testid="cellInnerDiv" and .//article]')
            try_num = 0  # 记录获取失败的贴文数量
            while select_num < num :
                self.driver.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", article)
                time.sleep(random.uniform(1,3))
                article_url = article.find_element(By.XPATH,'.//a[contains(@class,"css-146c3p1 r-bcqeeo r-1ttztb7 r-qvutc0 ")]').get_attribute("href")
                # nickname = article.find_element(By.XPATH,'.//div[@class="css-175oi2r r-1awozwy r-18u37iz r-1wbh5a2 r-dnmrzs"]').text.strip()   # css-175oi2r r-4qtqp9 r-zl2h9q   replying
                try:
                    article.find_element(By.XPATH,'.//div[contains(text(),"Replying to ")]')
                    self.log.info(f'该推文是用户的评论内容')
                    tweet_type = "replying"
                except:
                    tweet_type = ''
                    pass
                if try_num == 5:  # 连续获取5次失败，则直接返回
                    return create_response(create_time=create_time,code=HTTPStatus.OK,message='success',response=all_content)
                self.driver.open_new_tab(url=article_url)
                time.sleep(random.uniform(5,10))
                self.driver.swith_to_new_window(id=-1)
                data = await self.get_one_content()
                if not data:
                    self.log.info(f'{article_url} 未获得有效的帖子内容，继续获取下一个曝光帖子')
                    self.driver.close()
                    self.driver.swith_to_new_window(id=-1)
                    time.sleep(random.uniform(2,4))
                    article = article.find_element(By.XPATH,'following-sibling::div[@class="css-175oi2r" and @data-testid="cellInnerDiv" and .//article]')
                    try_num +=1
                    continue
                self.log.info(f'搜索热搜词{keyword}获取的曝光内容是:{data}')
                self.driver.close()
                self.driver.swith_to_new_window(id=-1)
                time.sleep(random.uniform(2,4))
                data["keyword"] = keyword
                data['tweet_type'] = tweet_type
                # data['note_url'] = data['note_url'] + f'/{tweet_type}'
                all_content.append(data)
                select_num += 1
                try_num = 0  # 获取贴文成功，则重置
                # 如果since_time.则比较时间是否符合time_limit
                if since_time:
                    if datetime.strptime(data["post_time_ip"], '%Y-%m-%dT%H:%M:%S.%fZ') > since_time: # 时间符合time_limit，则添加到曝光表中，并继续获取
                        pass
                    else: 
                        break  # 时间不符合time_limit，则结束循环 

                # 添加到曝光表中
                insert_sql = '''INSERT INTO `twitter_records`(`Account_id`,`Platform`,`URL`,`Source_account`,`Content`,`Likes_Num`,`Transmits_Num`,`Views_Num`,`Bookmarks_Num`,`Comments_Num`,`Published_Time_IP`,`Type`,`Form`,`Images_URL`,`Update_time`) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s);'''
                self.database.operation(insert_sql,(account_id,'twitter',data["note_url"],data["nickname"],data["content"],data["likes"],data["transmits"],data["views"],data["bookmarks"],data["comments"],data["post_time_ip"],data["note_type"],data["note_form"],str(data["images_url"]),datetime.now()))
                self.log.info('已更新twitter内容曝光表')
                try:
                    article = article.find_element(By.XPATH,'following-sibling::div[@class="css-175oi2r" and @data-testid="cellInnerDiv" and .//article]')
                    time.sleep(random.uniform(2,4))
                except:
                    self.log.info(f'已经滚动到页面底部，无更多曝光内容')
                    break  # 已经爬取到底部

            self.log.info(f'账号{account_id}检索{keyword}得到的{num}条曝光内容是：{all_content}')
            # 添加到互动表中
            insert_sql = '''INSERT INTO `twitter_interaction`(`Account_id`,`Platform`,`Content`,`Type`,`Action`,`URL`,`Interaction_time`,`Result_list`,`Update_time`) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s);'''
            self.database.operation(insert_sql,(account_id,'twitter',str(all_content),'关键词搜索','检索',None,action_time,None,datetime.now()))
            self.log.info(f'检索 已更新到数据库twitter互动表')
            return create_response(create_time=create_time,code=HTTPStatus.OK,message='success',response=all_content)
        except Exception as e:
            self.log.error(f'账号{account_id}获取热搜词{keyword}的内容失败，原因是{e}')
            return create_response(create_time=create_time,code=HTTPStatus.BAD_REQUEST,message='error',response=f'账号{account_id}获取关键词{keyword}的内容失败')
        


     
    async def scrap_content(self,account_id,url:str=None,keyword:str=None,num:int=10,time_limit:int=None,save_path:str=None):
        '''
        爬取某网页的曝光内容，支持：用户主页/关键字检索latest页面/home/热搜页面/某帖子页面
        -account_id: 账号id
        -url: 用户主页/热搜页面/帖子链接等,url为帖子链接时获取的是该帖子的评论
        -keyword: 关键字，不为None时则表示根据关键字检索
        -num: 获取帖子数量
        -time_limit:  int，表示几天前
        -save_path: 保存路径，默认为None
        '''

        try:
            create_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if 'https://x.com/' not in self.driver.driver.current_url:
                await self.login_by_cookies(account_id=account_id)
            action_time = datetime.now()
            if keyword and not url:
                self.log.info(f'检索关键字{keyword}获取贴文内容')
                url = f"https://twitter.com/search?q={keyword}&src=typed_query&f=live"  # 选择 Latest
            elif not url and not keyword:
                self.log.info(f'默认在首页滑动')
                url = 'https://x.com/home'
            else:
                self.log.info(f'在{url}网页滑动')
            

            # 进入网页
            self.driver.get(url = url)
            time.sleep(random.uniform(8,12))

            
 
            num = num if num else 1000000
            action = '关键字检索'  if keyword else '滑动'

            select_num = 0
            results = []
            since_time = None

            if time_limit is not None:
                end_time=convert_time_us(datetime.now())  
                since_time = end_time - timedelta(days=time_limit)
                self.log.info(f"开始获取账号{url} {since_time} 到现在 {end_time} 的推文")

            if 'communities' in url:
                # 点击latest
                self.driver.find_xpaths(XPATH='//div[@class="css-175oi2r r-14tvyh0 r-cpa5s6 r-16y2uox" and @role="presentation"]')[1].click()
                time.sleep(random.uniform(2,4))

            if '/status/' in url: 
                # 某个帖子，爬取帖子和其下边的相关评论
                data = await self.get_one_content()
                results.append(data)
                select_num += 1
                insert_sql = '''INSERT INTO `twitter_records`(`Account_id`,`Platform`,`URL`,`Source_account`,`Content`,`Likes_Num`,`Transmits_Num`,`Views_Num`,`Bookmarks_Num`,`Comments_Num`,`Published_Time_IP`,`Type`,`Form`,`Images_URL`,`Update_time`) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s);'''
                self.database.operation(insert_sql,(account_id,'twitter',data["note_url"],data["nickname"],data["content"],data["likes"],data["transmits"],data["views"],data["bookmarks"],data["comments"],data["post_time_ip"],data["note_type"],data["note_form"],str(data["images_url"]),datetime.now()))
                self.log.info('已更新twitter内容曝光表')
                try:
                    article = self.driver.find_xpaths(XPATH='//div[@class="css-175oi2r" and @data-testid="cellInnerDiv" and .//article]')[1] # 第一个回复
                except:
                    # 说明该贴文下无评论内容，曝光内容就只有贴文
                    self.log.info(f'账号{account_id}在网页{url}获取到的{num}条曝光内容是：{results}')
                     # 添加到互动表中
                    insert_sql = '''INSERT INTO `twitter_interaction`(`Account_id`,`Platform`,`Content`,`Type`,`Action`,`URL`,`Interaction_time`,`Result_list`,`Update_time`) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s);'''
                    self.database.operation(insert_sql,(account_id,'twitter',str(results),None,'滑动',url,action_time,None,datetime.now()))
                    self.log.info(f'滑动 已更新到数据库twitter互动表') 
                    return create_response(create_time=create_time,code=HTTPStatus.OK,message='success',response=results)
            else:  # 用户主页/home首页/关键字检索页面
                try:
                    article = self.driver.find_xpath(XPATH='//div[@class="css-175oi2r" and @data-testid="cellInnerDiv" and .//article]')
                except:
                    self.log.info(f'无相关贴文内容，直接返回')
                    return create_response(create_time=create_time,code=HTTPStatus.OK,message='success',response=results)

            reposted_num = 0
            while select_num < num:
                self.driver.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", article)
                time.sleep(random.uniform(2,4))
                # try:
                #     article_text = article.text
                # except:# 重新定位article元素
                #     article = self.driver.find_xpath(XPATH='//div[@class="css-175oi2r" and @data-testid="cellInnerDiv" and .//article]')
                #     self.driver.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", article)
                #     article_text = article.text
                
                if 'Pinned' in article.text:
                    self.log.info(f'跳过置顶帖子')
                    article = article.find_element(By.XPATH,'following-sibling::div[@class="css-175oi2r" and @data-testid="cellInnerDiv" and .//article]')
                    continue
                
                try:
                    article.find_element(By.XPATH,'.//div[contains(text(),"Replying to ")]')
                    self.log.info(f'该推文是用户的评论内容')
                    tweet_type = "replying"
                except:
                    tweet_type = ''
                    pass
                
                # 如果是广告，则跳过
                try:
                    article.find_element(By.XPATH,'.//div[@class="css-175oi2r r-1kkk96v"].//span[contains(text(),"Ad")]')
                    self.log.info(f'该推文是广告，跳过')
                    article = article.find_element(By.XPATH,'following-sibling::div[@class="css-175oi2r" and @data-testid="cellInnerDiv" and .//article]')
                    continue
                except:
                    pass

                # 获取贴文链接
                article_url = article.find_element(By.XPATH,'.//a[contains(@class,"css-146c3p1 r-bcqeeo r-1ttztb7 r-qvutc0 ") and contains(@href,"/status/")]').get_attribute("href")
        
                
                self.driver.open_new_tab(url=article_url)
                time.sleep(random.uniform(6,10))
                self.driver.swith_to_new_window(id=-1)
                time.sleep(random.uniform(1,3))
                data = await self.get_one_content()   # 获取贴文内容
                self.driver.close()
                time.sleep(random.uniform(1,3))
                self.driver.swith_to_new_window(id=-1)
                time.sleep(random.uniform(2,4))
                if not data:
                    self.log.info(f'未获得有效的帖子内容，继续获取下一个曝光帖子')
                    article = article.find_element(By.XPATH,'following-sibling::div[@class="css-175oi2r" and @data-testid="cellInnerDiv" and .//article]')
                    time.sleep(random.uniform(1,3))
                    continue
                try:
                    article.find_element(By.XPATH,'.//span[contains(text(),"reposted")]')
                    data["note_type"] = '快转'
                except:
                    pass
                
                data["keyword"] = keyword if keyword else ''
                data['tweet_type'] = tweet_type
                self.log.info(f'获取的曝光内容是:{data}')

                # 判断时间是否符合since_time
                if since_time:
                    if datetime.strptime(data["post_time_ip"], '%Y-%m-%dT%H:%M:%S.%fZ') < since_time:
                        self.log.info(f'since_time: {since_time}，帖子时间: {data["post_time_ip"]}，帖子时间早于since_time，停止获取帖子')
                        self.log.info("已经获取到{}天前的推文".format(time_limit))
                        insert_sql = '''INSERT INTO `twitter_interaction`(`Account_id`,`Platform`,`Content`,`Type`,`Action`,`URL`,`Interaction_time`,`Result_list`,`Update_time`) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s);'''
                        self.database.operation(insert_sql,(account_id,'twitter',str(results),None,action,url,action_time,None,datetime.now()))
                        self.log.info(f'{action} 已更新到数据库twitter互动表')
                        return create_response(create_time=create_time,code=HTTPStatus.OK,message='success',response=results)
                    if data["note_type"] == '快转' and since_time and datetime.strptime(data["post_time_ip"], '%Y-%m-%dT%H:%M:%S.%fZ') < since_time:
                        # 连续获得多个reposted的贴文 进行计数，如果计数=3则说明获取到{}天前的推文
                        reposted_num += 1
                        pass   
                if reposted_num == 3:
                    self.log.info("已经获取到{}天前的推文".format(time_limit))
                    insert_sql = '''INSERT INTO `twitter_interaction`(`Account_id`,`Platform`,`Content`,`Type`,`Action`,`URL`,`Interaction_time`,`Result_list`,`Update_time`) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s);'''
                    self.database.operation(insert_sql,(account_id,'twitter',str(results),None,action,url,action_time,None,datetime.now()))
                    self.log.info(f'{action} 已更新到数据库twitter互动表')
                    return create_response(create_time=create_time,code=HTTPStatus.OK,message='success',response=results)

                results.append(data)
                select_num += 1
                # 写到文件中
                if save_path:
                    with open(save_path, "a",encoding='utf-8') as file:
                        file.write(json.dumps(data, ensure_ascii=False) + "\n")
                        self.log.info(f'贴文{data}已经写入文件{save_path}')
                
                # 查询曝光表中是否已经存在该条贴文，若存在，则不再继续插入 
                sql = f'''SELECT * FROM twitter_interaction WHERE Account_id ={int(account_id)} AND URL = '{data["note_url"]}';'''
                select_result = self.database.get_dict_data_sql(sql)
                if not select_result:
                    insert_sql = '''INSERT INTO `twitter_records`(`Account_id`,`Platform`,`URL`,`Source_account`,`Content`,`Likes_Num`,`Transmits_Num`,`Views_Num`,`Bookmarks_Num`,`Comments_Num`,`Published_Time_IP`,`Type`,`Form`,`Images_URL`,`Update_time`) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s);'''
                    self.database.operation(insert_sql,(account_id,'twitter',data["note_url"],data["nickname"],data["content"],data["likes"],data["transmits"],data["views"],data["bookmarks"],data["comments"],data["post_time_ip"],data["note_type"],data["note_form"],str(data["images_url"]),datetime.now()))
                    self.log.info('已更新twitter内容曝光表')
                else:
                    self.log.info(f'数据在twitter内容曝光表中已经存在')
                try:
                    article = article.find_element(By.XPATH,'following-sibling::div[@class="css-175oi2r" and @data-testid="cellInnerDiv" and .//article]')
                    time.sleep(random.uniform(3,5))
                except:
                    self.log.info(f'已经滚动到页面底部，无更多曝光内容')
                    break  # 已经爬取到底部
            # 添加到互动表中
            insert_sql = '''INSERT INTO `twitter_interaction`(`Account_id`,`Platform`,`Content`,`Type`,`Action`,`URL`,`Interaction_time`,`Result_list`,`Update_time`) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s);'''
            self.database.operation(insert_sql,(account_id,'twitter',str(results),None,action,url,action_time,None,datetime.now()))
            self.log.info(f'{action} 已更新到数据库twitter互动表')
            self.log.info(f'账号{account_id}在网页{url}获取到的{num}条曝光内容是：{results}') 
            return create_response(create_time=create_time,code=HTTPStatus.OK,message='success',response=results)
        except Exception as e:
            self.log.info(f'账号{account_id}滑动页面，获取曝光内容失败，原因是：{e}')     
            return create_response(create_time=create_time,code=HTTPStatus.BAD_REQUEST,message='error',response=f'账号{account_id}滑动页面，获取曝光内容失败')
        
     


    # async def scrap_content_old(self,account_id,url=None,keyword=None,num=10,time_limit=None,save_path=None):
    #     '''爬取某网页url的num条内容，url可以是用户主页/热搜页面等,默认是爬取首页Home'''
    #     try:
    #         create_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    #         if 'https://x.com/' not in self.driver.driver.current_url:
    #             await self.login_by_cookies(account_id=account_id)
    #         action_time = datetime.now()
    #         if keyword and not url:
    #             self.log.info(f'检索关键字{keyword}获取贴文内容')
    #             url = f"https://twitter.com/search?q={keyword}&src=typed_query&f=live"  # 选择 Latest
    #         elif not url and not keyword:
    #             self.log.info(f'默认在首页滑动')
    #             url = 'https://x.com/home'
    #         elif url:
    #             self.log.info(f'在{url}网页滑动')
    #         # 进入网页
    #         self.driver.get(url = url)
    #         time.sleep(random.uniform(8,12))
    #         pdb.set_trace()
    #         if num == None:
    #             num  =  1000000
    #         select_num = 0
    #         results = []
    #         since_time = None
    #         if time_limit is not None:
    #             end_time=convert_time_us(datetime.now())  
    #             since_time = end_time - timedelta(days=time_limit)
    #             self.log.info(f"开始获取在{url} 从{since_time} 到现在 {end_time} 的推文")

    #         if '/status/' in url: 
    #             # 某个帖子，爬取帖子和其下边的相关评论
    #             data = await self.get_one_content()
    #             results.append(data)
    #             select_num += 1
    #             insert_sql = '''INSERT INTO `twitter_records`(`Account_id`,`Platform`,`URL`,`Source_account`,`Content`,`Likes_Num`,`Transmits_Num`,`Views_Num`,`Bookmarks_Num`,`Comments_Num`,`Published_Time_IP`,`Type`,`Form`,`Images_URL`,`Update_time`) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s);'''
    #             self.database.operation(insert_sql,(account_id,'twitter',data["note_url"],data["nickname"],data["content"],data["likes"],data["transmits"],data["views"],data["bookmarks"],data["comments"],data["post_time_ip"],data["note_type"],data["note_form"],str(data["images_url"]),datetime.now()))
    #             self.log.info('已更新twitter内容曝光表')
    #             try:
    #                 article = self.driver.find_xpaths(XPATH='//div[@class="css-175oi2r" and @data-testid="cellInnerDiv" and .//article]')[1] # 第一个回复
    #             except:
    #                 # 说明该贴文下无评论内容，曝光内容就只有贴文
    #                 self.log.info(f'账号{account_id}在网页{url}获取到的{num}条曝光内容是：{results}')
    #                  # 添加到互动表中
    #                 insert_sql = '''INSERT INTO `twitter_interaction`(`Account_id`,`Platform`,`Content`,`Type`,`Action`,`URL`,`Interaction_time`,`Result_list`,`Update_time`) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s);'''
    #                 self.database.operation(insert_sql,(account_id,'twitter',str(results),None,'滑动',url,action_time,None,datetime.now()))
    #                 self.log.info(f'滑动 已更新到数据库twitter互动表') 
    #                 return create_response(create_time=create_time,code=HTTPStatus.OK,message='success',response=results)
    #         else:  # 用户主页/home首页
    #             article = self.driver.find_xpath(XPATH='//div[@class="css-175oi2r" and @data-testid="cellInnerDiv" and .//article]')
    #         reposted_num = 0
    #         while select_num < num:
    #             self.driver.scroll(size=random.uniform(20,50))
    #             self.driver.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", article)
    #             time.sleep(random.uniform(2,4))
    #             try:
    #                 article_text = article.text
    #             except:# 重新定位article元素
    #                 article = self.driver.find_xpath(XPATH='//div[@class="css-175oi2r" and @data-testid="cellInnerDiv" and .//article]')
    #                 self.driver.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", article)
    #                 article_text = article.text
                
    #             if 'Pinned' in article_text:
    #                 self.log.info(f'跳过置顶帖子')
    #                 article = article.find_element(By.XPATH,'following-sibling::div[@class="css-175oi2r" and @data-testid="cellInnerDiv" and .//article]')
    #                 continue
                
    #             # 如果是repost的帖子，则会有两个url，只选择帖子链接
    #             # try:
    #             #     article.find_element(By.XPATH,'.//div[@class="css-175oi2r r-15zivkp r-q3we1"]')
    #             #     self.log.info(f'该帖子是 repost 贴文，获取贴文的链接')
    #             #     article_url = article.find_elements(By.XPATH,'.//a[contains(@class,"css-146c3p1 r-bcqeeo r-1ttztb7 r-qvutc0 ") and contains(@href,"/status/")]')[-1].get_attribute("href")
    #             # except:
    #             #     self.log.info(f'该帖文是作者的原创/转发贴文')
    #             #     article_url = article.find_element(By.XPATH,'.//a[contains(@class,"css-146c3p1 r-bcqeeo r-1ttztb7 r-qvutc0 ")]').get_attribute("href")
                
    #             # 获取贴文链接
    #             article_url = article.find_element(By.XPATH,'.//a[contains(@class,"css-146c3p1 r-bcqeeo r-1ttztb7 r-qvutc0 ") and contains(@href,"/status/")]').get_attribute("href")
        
    #             
    #             self.log.info(f'进入帖子链接：{article_url}')
    #             self.driver.open_new_tab(url=article_url)
    #             time.sleep(random.uniform(6,10))
    #             self.driver.swith_to_new_window(id=-1)
    #             time.sleep(random.uniform(1,3))
    #             data = await self.get_one_content()
    #             time.sleep(2)
    #             self.driver.close()
    #             time.sleep(random.uniform(1,3))
    #             self.driver.swith_to_new_window(id=-1)
    #             time.sleep(random.uniform(2,4))
    #             if not data:
    #                 self.log.info(f'未获得有效的帖子内容，继续获取下一个曝光帖子')
    #                 article = article.find_element(By.XPATH,'following-sibling::div[@class="css-175oi2r" and @data-testid="cellInnerDiv" and .//article]')
    #                 time.sleep(random.uniform(3,5))
    #                 continue
    #             try:
    #                 article.find_element(By.XPATH,'.//span[contains(text(),"reposted")]')
    #                 data["note_type"] = '快转'
    #             except:
    #                 pass

    #             self.log.info(f'获取的曝光内容是:{data}')

    #             # 判断时间
    #             # if data["note_type"] != '快转':
    #             if since_time and datetime.strptime(data["post_time_ip"], '%Y-%m-%dT%H:%M:%S.%fZ') < since_time:
    #                 self.log.info(f'since_time: {since_time}，帖子时间: {data["post_time_ip"]}，帖子时间早于since_time，停止获取帖子')
    #                 self.log.info("已经获取到{}天前的推文".format(time_limit))
    #                 insert_sql = '''INSERT INTO `twitter_interaction`(`Account_id`,`Platform`,`Content`,`Type`,`Action`,`URL`,`Interaction_time`,`Result_list`,`Update_time`) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s);'''
    #                 self.database.operation(insert_sql,(account_id,'twitter',str(results),None,'滑动',url,action_time,None,datetime.now()))
    #                 self.log.info(f'滑动 已更新到数据库twitter互动表')
    #                 return create_response(create_time=create_time,code=HTTPStatus.OK,message='success',response=results)
    #             if data["note_type"] == '快转' and since_time and datetime.strptime(data["post_time_ip"], '%Y-%m-%dT%H:%M:%S.%fZ') < since_time:
    #                 # 连续获得多个reposted的贴文 进行计数，如果计数=3则说明获取到{}天前的推文
    #                 reposted_num += 1
    #                 pass  # 继续执行写入数据库/文件等操作
    #             if reposted_num == 3:
    #                 self.log.info("已经获取到{}天前的推文".format(time_limit))
    #                 insert_sql = '''INSERT INTO `twitter_interaction`(`Account_id`,`Platform`,`Content`,`Type`,`Action`,`URL`,`Interaction_time`,`Result_list`,`Update_time`) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s);'''
    #                 self.database.operation(insert_sql,(account_id,'twitter',str(results),None,'滑动',url,action_time,None,datetime.now()))
    #                 self.log.info(f'滑动 已更新到数据库twitter互动表')
    #                 return create_response(create_time=create_time,code=HTTPStatus.OK,message='success',response=results)

    #             results.append(data)
    #             select_num += 1
    #             # 写到文件中
    #             if save_path:
    #                 with open(save_path, "a",encoding='utf-8') as file:
    #                     file.write(json.dumps(data, ensure_ascii=False) + "\n")
    #                     self.log.info(f'贴文{data}已经写入文件{save_path}')
    #             # 添加到曝光表中
    #             sql = f'''SELECT * FROM twitter_interaction WHERE Account_id ={int(account_id)} AND URL = '{data["note_url"]}';'''
    #             select_result = self.database.get_dict_data_sql(sql)
    #             if not select_result:
    #                 insert_sql = '''INSERT INTO `twitter_records`(`Account_id`,`Platform`,`URL`,`Source_account`,`Content`,`Likes_Num`,`Transmits_Num`,`Views_Num`,`Bookmarks_Num`,`Comments_Num`,`Published_Time_IP`,`Type`,`Form`,`Images_URL`,`Update_time`) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s);'''
    #                 self.database.operation(insert_sql,(account_id,'twitter',data["note_url"],data["nickname"],data["content"],data["likes"],data["transmits"],data["views"],data["bookmarks"],data["comments"],data["post_time_ip"],data["note_type"],data["note_form"],str(data["images_url"]),datetime.now()))
    #                 self.log.info('已更新twitter内容曝光表')
    #             else:
    #                 self.log.info(f'数据在twitter内容曝光表中已经存在')
    #             try:
    #                 article = article.find_element(By.XPATH,'following-sibling::div[@class="css-175oi2r" and @data-testid="cellInnerDiv" and .//article]')
    #                 time.sleep(random.uniform(3,5))
    #             except:
    #                 self.log.info(f'已经滚动到页面底部，无更多曝光内容')
    #                 break  # 已经爬取到底部
    #         # 添加到互动表中
    #         insert_sql = '''INSERT INTO `twitter_interaction`(`Account_id`,`Platform`,`Content`,`Type`,`Action`,`URL`,`Interaction_time`,`Result_list`,`Update_time`) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s);'''
    #         self.database.operation(insert_sql,(account_id,'twitter',str(results),None,'滑动',url,action_time,None,datetime.now()))
    #         self.log.info(f'滑动 已更新到数据库twitter互动表')
    #         self.log.info(f'账号{account_id}在网页{url}获取到的{num}条曝光内容是：{results}') 
    #         return create_response(create_time=create_time,code=HTTPStatus.OK,message='success',response=results)
    #     except Exception as e:
    #         self.log.info(f'账号{account_id}滑动页面，获取曝光内容失败，原因是：{e}')     
    #         return create_response(create_time=create_time,code=HTTPStatus.BAD_REQUEST,message='error',response=f'账号{account_id}滑动页面，获取曝光内容失败')
        



        
    async def get_account_character(self,account_id):
        '''从数据库中获取账号的人设'''
        try:
            create_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            sql = f"SELECT * FROM accounts_info WHERE Account_id = {account_id}"
            result = self.database.get_dict_data_sql(sql)
            person_id = result[0]["person_id"]
            if not person_id:
                self.log.info(f'账号{account_id}暂时无人设')
                return create_response(create_time=create_time,code=HTTPStatus.OK,message='success',response=f'账号{account_id}暂时无人设')
            database = sql_dataset("person")
            sql = f"SELECT * FROM person WHERE Id = {person_id}"
            characters = database.get_dict_data_sql(sql)[0]["Descriptions"]
            self.log.info(f'账号{account_id}的人设是：{characters}')
            return create_response(create_time=create_time,code=HTTPStatus.OK,message='success',response=characters)
        except Exception as e:
            self.log.info(f'获取账号{account_id}的人设失败，原因是：{e}')     
            return create_response(create_time=create_time,code=HTTPStatus.BAD_REQUEST,message='error',response=f'获取账号{account_id}人设失败')
        
        
    async def get_account_history(self,account_id):
        '''从数据库中获取账号的历史曝光'''
        try:
            create_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            sql = f"SELECT * FROM twitter_records WHERE Account_id = {account_id}"
            result = self.database.get_dict_data_sql(sql)
            if not result:
                self.log.info(f'账号{account_id}暂时无历史曝光')
                return create_response(create_time=create_time,code=HTTPStatus.OK,message='success',response=f'账号{account_id}暂时无历史曝光')
            for item in result:
                if isinstance(item.get('Update_time'), datetime):
                    item['Update_time'] = item['Update_time'].strftime('%Y-%m-%d %H:%M:%S')
            self.log.info(f'账号{account_id}的历史曝光是：{result}')
            return create_response(create_time=create_time,code=HTTPStatus.OK,message='success',response=result)
        except Exception as e:
            self.log.info(f'获取账号{account_id}的历史曝光失败，原因是：{e}')     
            return create_response(create_time=create_time,code=HTTPStatus.BAD_REQUEST,message='error',response=f'获取账号{account_id}历史曝光失败')



    async def get_account_interaction(self,account_id,sql:str=None):
        '''从数据库中获取账号的历史交互'''
        try:
            
            create_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if not sql:
                sql = f"SELECT * FROM twitter_interaction WHERE Account_id = {account_id}"
            result = self.database.get_dict_data_sql(sql)
            if not result:
                self.log.info(f'账号{account_id}暂时无历史交互内容')
                return create_response(create_time=create_time,code=HTTPStatus.OK,message='success',response=f'账号{account_id}暂时无历史交互内容')
            # 将datetime类型的数据修改为str
            for item in result:
                if isinstance(item.get('Interaction_time'), datetime):
                    item['Interaction_time'] = item['Interaction_time'].strftime('%Y-%m-%d %H:%M:%S')
                if isinstance(item.get('Update_time'), datetime):
                    item['Update_time'] = item['Update_time'].strftime('%Y-%m-%d %H:%M:%S')
            self.log.info(f'账号{account_id}的历史交互内容是：{result}')
            return create_response(create_time=create_time,code=HTTPStatus.OK,message='success',response=result)
        except Exception as e:
            self.log.info(f'获取账号{account_id}的历史交互内容失败，原因是：{e}')     
            return create_response(create_time=create_time,code=HTTPStatus.BAD_REQUEST,message='error',response=f'获取账号{account_id}历史交互内容失败')
      
        
    async def update_account_interest(self,account_id,interest):
        '''更新账号的兴趣,并将现有兴趣加入到历史兴趣中'''
        if isinstance(interest,str):
            interest = [interest] # 变成list
        try:
            create_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            sql = f"SELECT * FROM social_attributes WHERE Account_id = {account_id}"
            result = self.database.get_dict_data_sql(sql)
            if not result:
                self.log.info(f'数据库中暂无账号{account_id}的社交属性信息')
                return create_response(create_time=create_time,code=HTTPStatus.BAD_REQUEST,message='error',response=f'数据库中暂无账号{account_id}的社交属性信息')
            old_interest = result[0]["Interest"]
            if not old_interest: # 第一次更新兴趣/添加兴趣
                self.log.info(f'更新账号{account_id}的兴趣')
                update_sql = '''UPDATE social_attributes SET Interest = %s ,Update_time = %s WHERE Account_id = %s;'''
                self.database.operation(update_sql,(str(interest),datetime.now(),account_id))
                self.log.info(f'账号{account_id}的兴趣已更新为{interest}')
            else:
                history_interest = eval(result[0]["History_interest"])  if result[0]["History_interest"] else []
                old_interest = eval(old_interest)
                history_interest.append(old_interest)
                update_sql = '''UPDATE social_attributes SET Interest = %s,History_interest = %s,Update_time = %s WHERE Account_id = %s;'''
                self.database.operation(update_sql,(str(interest),str(history_interest),datetime.now(),account_id))
                self.log.info(f'账号{account_id}的兴趣已更新为{interest},历史兴趣已更新为：{history_interest}')
            return create_response(create_time=create_time,code=HTTPStatus.OK,message='success',response=f'账号{account_id}的兴趣更新成功')
        except Exception as e:
            self.log.info(f'账号{account_id}的兴趣更新失败，原因是：{e}')     
            return create_response(create_time=create_time,code=HTTPStatus.BAD_REQUEST,message='error',response=f'账号{account_id}的兴趣更新失败')
    
    async def get_history_interests(self,account_id):
        '''获取账号account_id的历史兴趣'''
        try:
            create_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            sql = f'''SELECT History_interest FROM social_attributes WHERE Account_id = {account_id}'''
            result = self.database.get_dict_data_sql(sql)
            if not result:
                self.log.info(f'数据库中暂无账号{account_id}的社交属性信息')
                return create_response(create_time=create_time,code=HTTPStatus.BAD_REQUEST,message='error',response=f'数据库中暂无账号{account_id}的社交属性信息')
            else:
                history_interest = result[0]["History_interest"] 
                self.log.info(f'账号{account_id}的历史兴趣是：{history_interest}')
                return create_response(create_time=create_time,code=HTTPStatus.OK,message='success',response=history_interest)
        except Exception as e:
            self.log.info(f'获取账号{account_id}的历史兴趣失败，原因是：{e}')     
            return create_response(create_time=create_time,code=HTTPStatus.BAD_REQUEST,message='error',response=f'获取账号{account_id}历史兴趣失败')
    


    def get_user_following(self,account_id=None,url=None,type='following'):
        '''
        获取账号account_id或者/url的关注列表，并保存在txt文件中,type=following/follower，默认是获取关注列表
        '''
        
        results = [] # 存放最后的关注列表
        if account_id:
            sql = f'''SELECT URL FROM accounts_info WHERE Account_id = {account_id}'''
            profile = self.database.get_dict_data_sql(sql)[0]["URL"]
            if type == 'following':
                following_url = profile + '/following'
            elif type == 'follower':
                following_url = profile + "/followers"
            self.driver.get(url=following_url)
            time.sleep(random.uniform(7,14))
            self.log.info(f'获取账号{account_id}的关注列表/粉丝列表，并写入文件 ./information/followings/twitter/{account_id}_{type}.txt')
            os.makedirs(f'./information/followings',exist_ok=True)
            save_path = f'./information/followings/twitter/{account_id}_{type}.txt'
        else:
            if type == 'following':
                following_url = url + '/following'
            elif type == 'follower':
                following_url = url  + "/followers"
            # following_url = url + "/following"
            self.driver.get(url = following_url)
            time.sleep(random.uniform(7,14))
            nickname = url.split('/')[-1]
            self.log.info(f'获取账号{url}的关注列表/粉丝列表，并写入文件 ./information/followings/{nickname}/{type}.txt')
            os.makedirs(f'./information/followings/{nickname}',exist_ok=True)
            save_path = f'./information/followings/{nickname}/{type}.txt'
    
        following_element = self.driver.find_xpath(XPATH='//div[@class="css-175oi2r" and @data-testid="cellInnerDiv"]')
        try:
            while True:
                try:
                    user_url = following_element.find_element(By.XPATH, './/a[@role="link"]').get_attribute("href")
                    self.log.info("当前获取关注用户/粉丝用户为：{}".format(user_url))
                except:
                    return results
                
                if os.path.exists(save_path):
                    # 读取txt文件，避免重复
                    with open(save_path, "r", encoding="utf-8") as file:
                        exit_results = file.readlines()  
                        exit_results = [result.strip() for result in results]  # 去除每行末尾的换行符
                    if user_url not in exit_results:
                        results.append(user_url)
                        with open(save_path,"a",encoding="utf-8") as file:
                            file.write(user_url + "\n")
                else: # 直接写入
                    results.append(user_url)
                    with open(save_path,"a",encoding="utf-8") as file:
                        file.write(user_url + "\n")
                following_element =  following_element.find_element(By.XPATH,'following-sibling::div[@class="css-175oi2r" and @data-testid="cellInnerDiv"]')
                self.driver.scroll(size=following_element.size['height'])
                time.sleep(random.uniform(2,4))
                if self.driver.judge_bottom():
                    self.log.info("已滚动到页面底部")
                    return results
        except Exception as e:
            self.log.error(f"获取用户粉丝/关注列表失败:{e}")
            return results 


   
    # def is_relative_time(self,time_str):
    #     '''判断是否是相对时间'''
    #     relative_time_patterns = [
    #         r'(\d+)\s*minutes? ago',
    #         r'(\d+)\s*hours? ago',
    #         r'(\d+)\s*days? ago'
    #     ]
    #     for pattern in relative_time_patterns:
    #         if re.search(pattern, time_str):
    #             return True
    #     return False

    # def parse_relative_time(self,relative_time_str):
    #     '''
    #     解析相对时间，转换成实际发布时间
    #     返回:解析后的datetime
    #     '''
    #     # 获取当前的时间
    #     now_time = datetime.now()

    #     # 正则
    #     time_patterns = {
    #         'minute': re.compile(r'(\d+)\s*minutes? ago'),
    #         'hour': re.compile(r'(\d+)\s*hours? ago'),
    #         'day': re.compile(r'(\d+)\s*days? ago')
    #     }
    #     for unit, pattern in time_patterns.items():
    #         match = pattern.search(relative_time_str)
    #         if match:
    #             value = int(match.group(1))
    #             if unit == 'minute':
    #                 return now_time - relativedelta(minutes=value)
    #             elif unit == 'hour':
    #                 return now_time - relativedelta(hours=value)
    #             elif unit == 'day':
    #                 return now_time - relativedelta(days=value)


    # def parse_exact_date(self,date_str):
    #     '''解析具体日期'''
    #     try:
    #         return parser.parse(date_str)
    #     except ValueError:
    #         return None


    # def parse_time_str(self,time_str):
    #     '''解析时间'''
    #     if self.is_relative_time(time_str):
    #         # 解析相对时间
    #         post_time = self.parse_relative_time(time_str)
    #     else:
    #         # 解析绝对时间
    #         post_time = self.parse_exact_date(time_str)
    #     return post_time  # 返回datetime类型的时间
    
    # def get_topic_content_from_bbc(self,account_id):
    #     '''
    #     从bbc新闻网站上获取话题
    #     返回：topic_content[dict]     [{'topic':'', 'content':'', 'post_time':''}]
    #     '''
    #     news = {} 
    #     topic_content = []
    #     current_date = datetime.now().strftime("%Y-%m-%d")  # 获取当前日期
    #     try:
    #         self.driver.get('https://www.bbc.com/news/us-canada')  # 进入bbc官网
    #         time.sleep(10)
    #         # 滚动页面
    #         self.driver.scroll(size=200)
    #         time.sleep(2)
    #         
    #         self.log.info('选择最新的新闻')
    #         # 循环所有的页面
    #         for button in range(1,2):  # 只获取前2页的内容、
    #             # 显示等待 新闻面板
    #             latest_element = WebDriverWait(self.driver.driver,10).until(
    #                 EC.presence_of_element_located((By.XPATH,'//div[@data-testid="alaska-section"]'))
    #             )
    #             liverpool_elements_num = len(latest_element.find_elements(By.XPATH,'.//div[@data-testid="liverpool-card"]')) # 9
    #             # 循环所有的新闻，点击进新闻，并获取相关内容
    #             for index in range(liverpool_elements_num):  # 从0到8
    #                 liverpool_elements = self.driver.find_xpaths(XPATH='//div[@data-testid="liverpool-card"]')  # 新闻列表
    #                 time.sleep(5)
    #                 # 获取新闻标题
    #                 topic_item = liverpool_elements[index].find_element(By.XPATH,'.//h2[@data-testid="card-headline"]').text
    #                 topic_item = topic_item.replace('"', '').replace("'", '').replace('“', '').replace("”", '').replace("‘", '').replace("’", '')
    #                 self.log.info(f'开始获取第{(button-1)*liverpool_elements_num+index+1}个新闻的内容')
    #                 liverpool_elements[index].click()   # 进入新闻界面
    #                 time.sleep(5)
    #                 self.driver.driver.refresh()
    #                 time.sleep(3)
    #                 # 获取新闻内容
    #                 try:
    #                     # 发布的是视频内容   data-testid="video-page-player"
    #                     self.driver.find_xpath(XPATH='//div[@data-testid="video-page-player"]')  # 如果找到了视频元素
    #                     time.sleep(2)
    #                     self.log.info('是视频新闻，获取视频简介内容和时间')
    #                     # 先找到h1
    #                     note_form = '视频新闻'
    #                     h1_element = self.driver.driver.find_element(By.CSS_SELECTOR,'h1')
    #                     time.sleep(2)
    #                     div_element = h1_element.find_element(By.XPATH,'following-sibling::div')   # sc-9b10f25c-3 cdaUmY
    #                     time.sleep(2)
    #                     content = div_element.text.replace('\n','')
    #                     time_str = div_element.find_element(By.XPATH,'following-sibling::span').text
    #                     time.sleep(2)
    #                     post_time = self.parse_time_str(time_str).strftime('%Y-%m-%d %H:%M:%S') # 解析时间为字符串
    #                 except Exception as e:
    #                     # 文本新闻
    #                     try:
    #                         time_str_element = self.driver.find_xpath(XPATH='//time')  # time_str元素
    #                         time.sleep(3)
    #                         self.log.info('是文本新闻，获取新闻内容和时间')
    #                         time_str = time_str_element.text
    #                         note_form = '文本新闻'
    #                         post_time = self.parse_time_str(time_str).strftime('%Y-%m-%d %H:%M:%S') # 解析时间为字符串
    #                         # 获取新闻文本
    #                         text_block_elements = self.driver.find_xpaths(XPATH='//div[@data-component="text-block" and @class="sc-18fde0d6-0 dlWCEZ"]')
    #                         time.sleep(3)
    #                         content = ''  # 初始化一个空的content
    #                         for text_block_element in text_block_elements:
    #                             content = content + text_block_element.text.replace('\n','') 
    #                     except Exception as e:
    #                         self.log.info(f'查找新闻内容的时候出现错误:{e}')
    #                 # 添加进列表，后续写入文件保存
    #                 time.sleep(3)
    #                 # 去掉引号
    #                 content = content.replace('"', '').replace("'", '').replace('“', '').replace("”", '').replace("‘", '').replace("’", '')
    #                 # 获取新闻的链接
    #                 news_url = self.driver.driver.current_url
    #                 news = {'news': topic_item, 'content': content, 'post_time': post_time,"content_url":news_url}
    #                 self.log.info(f"bbc新闻内容为：{news}")
    #                 topic_content.append(news)
    #                 # 写入文件
    #                 os.makedirs(f"./information/bbc_news/", exist_ok=True)
    #                 with open(f"./information/bbc_news/{current_date}.json","a",encoding="utf-8") as file:
    #                     file.write(json.dumps(news, ensure_ascii=False) + "\n")

    #                 # 存入twittert的曝光数据表中
    #                 insert_sql = '''INSERT INTO `twitter_records`(`Account_id`,`Platform`,`URL`,`Content`,`Published_Time_IP`,`Form`,`Update_time`) VALUES(%s,%s,%s,%s,%s,%s,%s);'''
    #                 self.database.operation(insert_sql,(account_id,'bbc',news_url,topic_item + content,post_time,note_form,datetime.now()))
    #                 self.log.info('已更新twitter内容曝光表')

    #                 self.log.info(f'该新闻的时间是：{post_time}')
    #                 self.log.info('回到最开始的页面')
    #                 self.driver.get('https://www.bbc.com/news/us-canada')
    #                 # self.driver.go_back()
    #                 time.sleep(5)
    #                 # 点击相应的页面按钮
    #                 # 查看当前是否是button页
    #                 page_id = self.driver.find_xpath(XPATH='//button[@data-testid="pagination-back-button"]').text
    #                 self.log.info(f'当前在第{page_id}页，实际应该在第{button}页')
    #                 if int(page_id) == button:
    #                     continue # 是当前页，继续查找新闻
    #                 else:
    #                     # 点击到button页再查找新闻
    #                     self.driver.search_and_click(XPATH=f'//button[@class="sc-faaff782-1 sc-faaff782-2 dScmQm hPrIkI" and text()="{button}"]',waiting_time=2.0)
    #                     self.log.info(f'已经跳转到第{button}页，继续获取新闻内容')
                
    #             news_panel = self.driver.find_xpath(XPATH='//div[@class="sc-da05643e-0 kbaPPZ"]')   # 整个新闻面板
    #             # 点击下一页的按钮
    #             news_panel.find_element(By.XPATH,'.//button[@data-testid="pagination-next-button" and @aria-label="Next Page"]').click()
    #             time.sleep(5)
    #             self.log.info(f'第{button}页的话题已经获取完毕,进入到第{button+1}页继续获取新闻')
    #         return topic_content 
    #     except Exception as e:
    #         self.log.info(f'获取新闻失败:',{e}) 
    #         return []  # 空的列表[字典]  
        

    # def get_topic_content_from_cnn(self,account_id):
    #     '''
    #     从cnn网站上获取最新的美国政治新闻, 共能获取到46个新闻，随机选择10个
    #     返回：topic_content = [{'news': topic_item, 'content': content, 'post_time': post_time,"content_url":news_url}]
    #     '''
    #     news = {}
    #     topic_content = []
    #     urls_set = set()
    #     current_date = datetime.now().strftime("%Y-%m-%d")  # 获取当前日期
    #     try:
    #         self.driver.get(url = 'https://edition.cnn.com/politics') # CNN-> politics板块，获取latest新闻
    #         time.sleep(random.uniform(10,20))
    #         # 找到所有的a元素
    #         a_elements = self.driver.find_xpaths(XPATH='//a[@data-link-type="article"]')
    #         # 循环所有的a_element，保存其链接
    #         for a_element in a_elements:
    #             url = a_element.get_attribute("href")
    #             urls_set.add(url) 
    
    #         urls_list = list(urls_set)
    #         urls_list = random.sample(urls_list,10)  # 随机选择10个CNN新闻
    #         if urls_list:
    #             # 输出所有的链接
    #             self.log.info(f'从CNN上共获取到{len(urls_list)}个新闻链接')
    #             for url in urls_list:
    #                 self.log.info(f'获取第{urls_list.index(url)+1}条新闻{url}的内容')
    #                 self.driver.get(url = url)
    #                 time.sleep(random.uniform(5,10))

    #                 # 获取新闻标题
    #                 topic = self.driver.find_xpath(XPATH='//h1[@data-editable="headlineText"]').text
    #                 # 获取新闻发布时间,Updated 9:15 PM EDT, Thu September 19, 2024
    #                 time_str = self.driver.find_xpath(XPATH='//div[@class="timestamp vossi-timestamp"]').text 
    #                 # 获取新闻内容
    #                 content = self.driver.find_xpath(XPATH='//div[@class="article__content"]').text.replace('\n','')
    #                 # 去掉引号
    #                 content = content.replace('"', '').replace("'", '').replace('“', '').replace("”", '').replace("‘", '').replace("’", '')
    #                 news = {'news': topic, 'content': content, 'post_time': time_str,"content_url": url}
    #                 self.log.info(f"cnn新闻内容为：{news}")
    #                 topic_content.append(news)
    #                 # 存入twittert的曝光数据表中
    #                 insert_sql = '''INSERT INTO `twitter_records`(`Account_id`,`Platform`,`URL`,`Content`,`Published_Time_IP`,`Update_time`) VALUES(%s,%s,%s,%s,%s,%s);'''
    #                 self.database.operation(insert_sql,(account_id,'bbc',url,topic + content,time_str,datetime.now()))
    #                 self.log.info('已更新twitter内容曝光表')
    #                 os.makedirs(f"./information/cnn_news/", exist_ok=True)
    #                 with open(f"./information/cnn_news/{current_date}.json","a",encoding="utf-8") as file:
    #                     file.write(json.dumps(news, ensure_ascii=False) + "\n")
    #         return topic_content
    #     except Exception as e:
    #         self.log.info(f'获取新闻失败:',{e}) 
    #         return topic_content  # 空的列表[字典] 
        
    
    def modify_passwd(self,account_id):
        "修改账户密码"
        try:
            
            search_sql = f"SELECT * FROM accounts_info WHERE accounts_info.Account_id = {account_id}"
            result = self.database.get_dict_data_sql(search_sql)[0]
            self.log.info("从数据库中获取到的账号信息:{}".format(result))
            password = result['Password']
            token = result['Token']
            self.driver.get(url="https://x.com/settings/password")
            self.log.info("进入修改密码页面")
            time.sleep(3)
            self.driver.send_content(XPATH='//input[@name="current_password"]',content = password)
            self.log.info(f"输入账户{account_id}当前密码:{password}")
            time.sleep(random.uniform(1,3))
            # 定义密码字符集
            characters = string.ascii_letters + string.digits + '!@#&.'
    
            # 随机选择字符生成密码68894bb47a8309b17c90bf7c36ed1aa88f7b9ff5
            
            new_password = ''.join(random.choice(characters) for i in range(12))
            self.log.info(f"账号{account_id}生成新密码:{new_password}")
            self.driver.send_content(XPATH='//input[@name="new_password"]',content = new_password)
            self.log.info("输入新密码")#csiIEJMYON6s
            time.sleep(random.uniform(1,3))
            self.driver.send_content(XPATH='//input[@name="password_confirmation"]',content = new_password)
            self.log.info("再次输入新密码")#tB4pzvyNNUq6
            time.sleep(random.uniform(1,3))
            self.driver.search_and_click(XPATH='//button[@data-testid="settingsDetailSave"]')
            self.log.info("点击保存")
            # sql = "UPDATE twitter_account SET Password = %s WHERE Id = %s"
            # self.database.operation(sql, (new_password, self.account_id))
            # self.log.info("更新数据库密码成功")
            time.sleep(random.uniform(1,3))
            cookies = self.driver.get_cookies(url="https://x.com/home")
            # 查找 auth_token
            auth_token = ''
            ct0 = ''
            for cookie in cookies:
                if cookie['name'] == 'auth_token':
                    auth_token = cookie['value']
                if cookie['name'] == 'ct0':
                    ct0 = cookie['value']
            self.log.info(f"账号{account_id}更新后的auth_token为：{auth_token}")
            cookies = json.dumps(cookies)
            time.sleep(random.uniform(1,3))
            sql = '''UPDATE accounts_info SET Password = %s, Token = %s, Ct0 = %s, Cookie = %s WHERE Account_id = %s'''
            self.database.operation(sql, (new_password,auth_token,ct0,cookies, account_id))
            self.log.info("更新数据库密码、cookies和auth_token成功")
        except Exception as e:
            self.log.error(f"账户{account_id}修改密码和token失败: {e}")


    def scroll(self,duration):
        '''在一个页面滑动时长'''
        start_time = time.time()
        while time.time() - start_time < duration:
            self.driver.scroll(size=random.uniform(100,500))
            time.sleep(random.uniform(0.5, 5))


    async def get_persons_by_keyword(self,account_id,keyword):
        '''根据关键字检索用户，获取用户的基本信息'''
        try:
            create_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if 'https://x.com' not in self.driver.driver.current_url:
                await self.login_by_cookies(account_id=account_id)
            url = f'''https://twitter.com/search?q="{keyword}"&src=typed_query&f=user'''
            
            all_persons = []   # [{}]

            self.driver.get(url=url)
            self.log.info("进入页面")
            time.sleep(random.uniform(8,12))
            self.log.info(f'获取 {keyword} 相关的用户')
            try:
                first_element = self.driver.find_xpath(XPATH='//div[@class="css-175oi2r" and @data-testid="cellInnerDiv"]')
            except:
                self.log.info(f'检索“{keyword}”未获得任何相关用户')
                return create_response(create_time=create_time,code=HTTPStatus.OK,message='success',response=all_persons)
            while True:
                self.driver.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", first_element)
                time.sleep(random.uniform(1,3))
                try:
                    person_url = first_element.find_element(By.TAG_NAME,'a').get_attribute("href")
                    nickname = first_element.find_element(By.XPATH,'.//div[@class="css-175oi2r r-1awozwy r-18u37iz r-dnmrzs"]').text.strip()
                    try:
                        user_description = first_element.find_element(By.XPATH,'.//div[@class="css-146c3p1 r-bcqeeo r-1ttztb7 r-qvutc0 r-37j5jr r-a023e6 r-rjixqe r-16dba41 r-1h8ys4a r-1jeg54m"]').text.strip().replace('\n','')
                    except:
                        user_description =  ''
                    person_info = {"url":person_url,"nickname":nickname,"description":user_description}
                    self.log.info(f'获得的相关用户是： {person_info}')
                    all_persons.append(person_info)
                    # 查找下一个用户
                    first_element = first_element.find_element(By.XPATH,'following-sibling::div[@class="css-175oi2r" and @data-testid="cellInnerDiv"]')
                    time.sleep(random.uniform(1,3))
                    continue
                except Exception as e:
                    self.log.info(f'已经查找完所有关于 {keyword} 的相关用户:{e}')
                    break
            self.log.info(f'检索“{keyword}”获得的相关用户有：{all_persons}')
            return create_response(create_time=create_time,code=HTTPStatus.OK,message='success',response=all_persons)
        except Exception as e:
            self.log.error(f'账号{account_id}检索关键词{keyword}获取用户失败，原因是{e}')
            return create_response(create_time=create_time,code=HTTPStatus.BAD_REQUEST,message='error',response=f'账号{account_id}获取关键词{keyword}的相关用户失败')




    async def get_communities_by_keyword(self,account_id,keyword,num:int=30):
        '''根据关键字检索社区，获取社区简介和成员个数等信息'''
        try:
            create_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if 'https://x.com' not in self.driver.driver.current_url:
                await self.login_by_cookies(account_id=account_id)
            url = f"https://x.com/i/communities/suggested?q={keyword}"
            
            all_communities = []   # [{}]

            self.driver.get(url=url)
            self.log.info("进入页面")
            await asyncio.sleep(random.uniform(10,15))
            self.log.info(f'获取 {keyword} 相关的社区')
            select_num = 0
            try:
                first_element = self.driver.find_xpath(XPATH='//div[@class="css-175oi2r" and @data-testid="cellInnerDiv"]')
            except:
                self.log.info(f'检索“{keyword}”未获得任何相关社区')
                return create_response(create_time=create_time,code=HTTPStatus.OK,message='success',response=all_communities)
            while True:
                self.driver.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", first_element)
                time.sleep(random.uniform(3,10))
                community_url = first_element.find_element(By.TAG_NAME,'a').get_attribute("href")
                self.driver.open_new_tab(url=community_url)
                time.sleep(random.uniform(10,15))
                self.driver.swith_to_new_window(id=-1)
                time.sleep(random.uniform(3,5))
                try:
                    self.driver.search_and_click(XPATH='//button[@class="css-175oi2r r-sdzlij r-1phboty r-rs99b7 r-lrvibr r-1mnahxq r-19yznuf r-64el8z r-1fkl15p r-1loqt21 r-o7ynqc r-6416eg r-1ny4l3l"]',waiting_time=random.uniform(3,5))
                    self.log.info(f'点击 check it out')
                except:
                    pass
                # 获取community的名字、简介、成员个数等信息
                try:
                    community_name = self.driver.find_xpath(XPATH='//div[@class="css-146c3p1 r-bcqeeo r-1ttztb7 r-qvutc0 r-37j5jr r-1yjpyg1 r-ueyrd6 r-b88u0q r-eqz5dr r-1obld4x r-15zivkp"]/span[1]').text.replace('\n','').strip()
                except:
                    community_name = ''
                try:
                    community_description = self.driver.find_xpath(XPATH='//div[@class="css-146c3p1 r-8akbws r-krxsd3 r-dnmrzs r-1udh08x r-1udbk01 r-bcqeeo r-1ttztb7 r-qvutc0 r-37j5jr r-a023e6 r-rjixqe r-16dba41"]').text.replace('\n','').strip()
                except:
                    community_description = ''
                try:
                    community_lable = self.driver.find_xpath(XPATH='//button[@class="css-175oi2r r-sdzlij r-1phboty r-rs99b7 r-lrvibr r-18u37iz r-5oul0u r-7xmw5f r-1ceczpf r-lp5zef r-3o4zer r-1loqt21 r-o7ynqc r-6416eg r-1ny4l3l"]').text.replace('\n','').strip()
                except:
                    community_lable = ''
                try:
                    members_num = self.driver.find_xpath(XPATH='//a[.//span[contains(text(),"Members")]]').text.replace('Members','').strip()
                except:
                    members_num = ''
                
                community_info =  {
                    "community_name": community_name,
                    "community_url": community_url,
                    "community_description": community_description,
                    "community_lable": community_lable,
                    "members_num": members_num,
                    "merbers_list": community_url+'/members'
                }
                self.log.info(f'检索关键字 {keyword} 获得的社区信息是：{community_info}')
                all_communities.append(community_info)
                select_num += 1
                if select_num  == num:
                    self.log.info(f'已经获取到 {select_num} 个社区的信息')
                    # 关闭该窗口
                    await self.close_now_windows()
                    break
                # 关闭该窗口
                await self.close_now_windows()
                try:
                    first_element =  first_element.find_element(By.XPATH,'following-sibling::div[@class="css-175oi2r" and @data-testid="cellInnerDiv"]')
                except:
                    self.log.info(f'已经获取完所有相关社区')
                    break
               
            self.log.info(f'检索“{keyword}”获得的相关社区有：{all_communities}')
            return create_response(create_time=create_time,code=HTTPStatus.OK,message='success',response=all_communities)
        except Exception as e:
            self.log.error(f'账号{account_id}检索关键词{keyword}获取社区失败，原因是{e}')
            return create_response(create_time=create_time,code=HTTPStatus.BAD_REQUEST,message='error',response=f'账号{account_id}获取关键词{keyword}的相关社区失败')
        



    async def get_communities_by_keyword_list(self,account_id,keyword,num:int=50):
        '''根据关键字检索社区，获取社区简介和成员个数等信息   这个代码是检索list的。。。暂时不用'''
        try:
            create_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if 'https://x.com' not in self.driver.driver.current_url:
                await self.login_by_cookies(account_id=account_id)
            url = f"https://twitter.com/search?q={keyword}&src=typed_query&f=list"
            
            all_communities = []   # [{}]

            self.driver.get(url=url)
            self.log.info("进入页面")
            time.sleep(random.uniform(8,12))
            # 再开一个一模一样的界面
            self.driver.open_new_tab(url=url)
            time.sleep(random.uniform(8,12))
            self.log.info(f'获取 {keyword} 相关的社区')
            self.driver.swith_to_new_window(id=0)
            time.sleep(1.5)
            select_num = 0
            try:
                first_element = self.driver.find_xpath(XPATH='//div[@class="css-175oi2r" and @data-testid="cellInnerDiv" and .//img]')
            except:
                self.log.info(f'检索“{keyword}”未获得任何相关社区')
                return create_response(create_time=create_time,code=HTTPStatus.OK,message='success',response=all_communities)
            while True:
                self.driver.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", first_element)
                time.sleep(random.uniform(1,3))
                # 获取该community的名字
                community_name = first_element.find_element(By.XPATH,'.//div[@class="css-175oi2r r-1awozwy r-18u37iz r-zl2h9q r-13qz1uu"]/div[1]').text.strip().replace('\n','')
                self.log.info(f'社区的名字是：{community_name}')
                time.sleep(random.uniform(1,3))
                try:
                    self.driver.swith_to_new_window(id=1)
                    time.sleep(random.uniform(2,5))
                    community_element = self.driver.find_xpath(XPATH=f'//div[.//span[contains(text(),"{community_name}")]]')
                    self.driver.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", community_element)
                    time.sleep(random.uniform(1,3))
                    self.driver.search_and_click(XPATH=f'//div[@class="css-175oi2r" and @data-testid="cellInnerDiv" and .//span[contains(text(),"{community_name}")]]',waiting_time=random.uniform(3,6))
                    # community_element.click()
                    # time.sleep(random.uniform(3,6))
                    #  获取community的信息：简介、成员数量、粉丝数量
                    community_url = self.driver.driver.current_url
                    community_description = self.driver.find_xpath(XPATH='//div[@class="css-175oi2r r-1awozwy r-18u37iz r-1777fci r-6gpygo r-13qz1uu"]').text.strip().replace('\n','')
                    members_num = self.driver.find_xpath(XPATH='//a[.//span[contains(text(),"Members")]]').text.replace('Members','').strip()
                    followers_num = self.driver.find_xpath(XPATH='//a[.//span[contains(text(),"Followers")]]').text.replace('Followers','').strip()
                    community_info =  {
                        "community_name": community_name,
                        "community_url": community_url,
                        "community_description": community_description,
                        "members_num": members_num,
                        "followers_num": followers_num,
                        "merbers_list": community_url+'/members',
                        "followers_list": community_url+'/followers'
                    }
                    self.log.info(f'检索关键字 {keyword} 获得的社区信息是：{community_info}')
                    all_communities.append(community_info)
                    select_num += 1
                    if select_num  == num:
                        self.log.info(f'已经获取到 {select_num} 个社区的信息')
                        break
                    self.log.info(f'点击返回按钮')
                    self.driver.search_and_click(XPATH='//div[@class="css-175oi2r r-1pz39u2 r-1777fci r-15ysp7h r-1habvwh r-s8bhmr"]/button',waiting_time=5.0)  # 点击返回按钮
                    # 切回到第一个窗口
                    self.driver.swith_to_new_window(id=0)
                    time.sleep(random.uniform(2,5))
                    try:
                         first_element =  first_element.find_element(By.XPATH,'following-sibling::div[@class="css-175oi2r" and @data-testid="cellInnerDiv" and .//img]')
                    except:
                        self.log.info(f'已经获取完所有相关社区')
                        break
                except:
                    self.log.info(f'已经获取完所有相关社区')
                    break
            self.log.info(f'检索“{keyword}”获得的相关社区有：{all_communities}')
            return create_response(create_time=create_time,code=HTTPStatus.OK,message='success',response=all_communities)
        except Exception as e:
            self.log.error(f'账号{account_id}检索关键词{keyword}获取社区失败，原因是{e}')
            return create_response(create_time=create_time,code=HTTPStatus.BAD_REQUEST,message='error',response=f'账号{account_id}获取关键词{keyword}的相关社区失败')





    def parse_time_string(self,time_string: str):
        """
        将时间字符串（例如 '2 hours', '30 minutes', '1 day'）解析为 datetime 对象。
        """
        # 正则表达式解析时间字符串中的数字和单位
        pattern = r"(\d+)\s*(hours?|minutes?|days?)"
        match = re.match(pattern, time_string.strip().lower())
        
        if match:
            quantity = int(match.group(1))  # 数字部分
            unit = match.group(2).lower()   # 单位部分（小时、分钟或天）
            
            if "hour" in unit:
                delta = timedelta(hours=quantity)
            elif "minute" in unit:
                delta = timedelta(minutes=quantity)
            elif "day" in unit:
                delta = timedelta(days=quantity)
            else:
                raise ValueError(f"时间字符串无效: {time_string}")
            
            # 获取当前时间，并减去相应的时间差
            current_time = datetime.now()
            target_time = current_time - delta
            return target_time
        else:
            raise ValueError(f"时间字符串无效: {time_string}")


    async def get_notifications_details(self,account_id,article):
        notify_information =  []  # 存放通知消息
        # 获取account_id的url
        select_sql = f'''SELECT URL FROM accounts_info WHERE Account_id = {account_id}'''
        account_url = self.database.get_dict_data_sql(select_sql)[0]['URL']
        
        notify_type = None
        try:
            notification_text = article.find_element(By.XPATH,'.//div[@class="css-146c3p1 r-bcqeeo r-1ttztb7 r-qvutc0 r-37j5jr r-a023e6 r-rjixqe r-16dba41 r-1udh08x"]').text.strip()
            notify_type = 'liked' if 'liked' in notification_text else 'reposted' if 'reposted' in notification_text else None
            self.log.info(f'该条通知是：用户{notify_type}帖子/{notify_type}评论')
        except:
            self.log.info(f'该通知不是liked和reposted')
            try:
                article.find_element(By.XPATH,'.//div[@class="css-175oi2r r-4qtqp9 r-zl2h9q"]')  # replying to xxx
                self.log.info(f'该条通知是：用户评论帖子/回复评论')
                notify_type =  'replied'
            except:
                self.log.info(f'该通知也不是replied')

        if not notify_type:
            self.log.info(f'该条通知是：新增用户关注 / twitter 广告')
            return []
        
        # 获取头像个数/用户名字
        div_elements = article.find_elements(By.XPATH,'.//div[@class="css-175oi2r r-sdzlij r-1udh08x r-5f1w11 r-u8s1d r-8jfcpp"]')
        if div_elements:
            actors_url = [div_element.find_element(By.TAG_NAME,'a').get_attribute("href") for div_element in div_elements]
        else:
            actors_url = [article.find_element(By.XPATH,'.//div[@data-testid="Tweet-User-Avatar"]').find_element(By.TAG_NAME,'a').get_attribute("href")]
        self.log.info(f'共有 {len(actors_url)} 个用户{notify_type}了帖子/评论')

        # 点击获取通知的具体内容(点击侧边栏)
        try:
            article.find_element(By.XPATH,'.//div[@class="css-175oi2r r-1ybcz0z r-6koalj r-9aw3ui"]').click()
        except:
            article.click()

        time.sleep(random.uniform(5,10))
        if notify_type == 'replied':
            note_info = await self.get_one_content() 
            note_info['notify_type'] =  notify_type   # replied
            note_info['actors_url'] = actors_url  # replied用户的主页链接urls
            # 获取被评论的帖子
            self.driver.scroll(size=-1000)
            time.sleep(random.uniform(3,5))
            # 找到自己发布的内容，然后获取链接和内容
            try:
                href = account_url.replace("https://x.com","")
                account_article = self.driver.find_xpath(XPATH=f'//article[@data-testid="tweet" and .//a[@href="{href}"]]')
                # 获取原帖的内容和链接
                note_info['original_content'] = account_article.find_element(By.XPATH,'.//div[@data-testid="tweetText"]').text.strip().replace('\n','')
                note_info['original_url'] = account_article.find_element(By.XPATH,'.//a[.//time]').get_attribute('href')
            except:
                pass
            # self.log.info(f'获得的帖子信息是：{note_info}')  
            # 存入数据库/文件
            notify_information.append(note_info)
            
        else:   # 点赞或者reposted
            # self.driver.scroll(size=500)
            # 获取所有的贴文
            details_element = self.driver.find_xpath(XPATH='//div[@class="css-175oi2r" and @data-testid="cellInnerDiv" and .//article]')
            # note_url = details_element.find_element(By.XPATH,'.//a[.//time]').get_attribute('href')
            href = account_url.replace("https://x.com","")
            account_article = self.driver.find_xpath(XPATH=f'//article[@data-testid="tweet" and .//a[@href="{href}"]]')
            note_url = account_article.find_element(By.XPATH,'.//a[.//time]').get_attribute('href')
            # 可能会存在多个用户点赞/转发同一篇内容
            while True:
                await asyncio.sleep(random.uniform(2,5))
                note_info = await self.get_one_content(url = note_url)
                for actor_url in actors_url:
                    data = note_info
                    data['notify_type'] =  notify_type    # reposted或者liked
                    data['actors_url'] = [actor_url]  # reposted或者liked的用户主页链接urls
                    data['original_content'] = data['content']  # 原帖的内容
                    data['original_url'] = data['note_url']  # 原帖的url
                    data['content'] = ''   # 评论内容为空
                    data['note_url'] = ''   # 评论的帖子链接为空
                    self.log.info(f'获取到的通知具体内容是：{data}')
                    notify_information.append(data) 

                # note_info['notify_type'] =  notify_type    # reposted或者liked
                # note_info['actors_url'] = actors_url  # reposted或者liked的用户主页链接urls
                # self.log.info(f'获取到的通知具体内容是：{note_info}')
                # notify_information.append(note_info)  # 将用户点赞/reposted的所有帖子信息都暂存到列表中，可更新数据库

                try:
                    details_element = details_element.find_element(By.XPATH,'following-sibling::div[@class="css-175oi2r" and @data-testid="cellInnerDiv" and .//article]')
                    self.driver.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", details_element)
                    await asyncio.sleep(random.uniform(1,3))
                    note_url = details_element.find_element(By.XPATH,'.//a[.//time]').get_attribute('href')
                except:
                    break


        return notify_information  # 返回获得的所有通知信息  # 可以加上用户等，找头像，获得操作对象的主页链接
    

    async def covert_ustime_to_china(self,time_str:str):
        '''将美国时间字符串转换成 中国北京时间，不带时区的时间,返回：datetime类型'''
        dt_utc = datetime.strptime(time_str, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
        dt_beijing = dt_utc.astimezone(timezone(timedelta(hours=8)))
        # 去掉时区信息，得到 naive datetime
        return dt_beijing.replace(tzinfo=None)


    async def get_notifications(self,account_id,time_limit):
        '''
        查看notifications,检查是存在未读消息，
        如果存在点赞，则更新记录表中，记录这条贴文的数据量
        如果存在评论，则返回url和对方评论的内容，然后进行回复
        
        -time_limit:通知开始的时间，可以为datetime/str类型，str类型支持：days,hours,minutes

        '''
        create_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if 'https://x.com' not in self.driver.driver.current_url:
            await self.login_by_cookies(account_id=account_id)

        notify_informations = []

        notifications = self.driver.find_xpath(XPATH='//a[@href="/notifications"]')
        try:
            notifications.find_element(By.XPATH,'.//div[contains(@aria-label,"unread items")]')
            self.log.info(f'存在未读通知, 点击Notifications')
            self.driver.get(url='https://x.com/notifications')
            await asyncio.sleep(random.uniform(5,8))
        except Exception as e:
            self.log.info(f'暂时不存在未读通知')
            return create_response(create_time=create_time,code=HTTPStatus.OK,message='success',response=notify_informations)   # 不存在新通知，则返回空list
        
        # time_limit转换成datetime类型的时间
        if isinstance(time_limit,str):
            notification_start_time = self.parse_time_string(time_string=time_limit)
        if isinstance(time_limit,datetime):
            notification_start_time = time_limit
        
        

        # 获取通知的具体内容
        try:
            action_time = datetime.now()  # 交互开始时间
            div_element = self.driver.find_xpath(XPATH='//div[@aria-label="Timeline: Notifications"]')
            first_article = div_element.find_element(By.XPATH,'//div[@class="css-175oi2r" and @data-testid="cellInnerDiv" and .//article]') # 获取第一个通知
            notify_time = first_article.find_element(By.TAG_NAME,'time').get_attribute('datetime')   # 第一个通知的时间 str
            # 转换成datetime类型
            notify_time = await self.covert_ustime_to_china(notify_time)

            if notify_time < notification_start_time:
                self.log.info(f'第一个通知的时间不符合{time_limit},不再继续获取通知')
                return create_response(create_time=create_time,code=HTTPStatus.OK,message='success',response=[])
            #  第一个的时间符合，则获取第一个的内容
            first_notification_information  =  await self.get_notifications_details(account_id=account_id,article=first_article)
            if len(first_notification_information) == 0:
                self.log.info(f'第一个通知是 用户关注/广告')
            else: 
                self.log.info(f'获取到的第一个通知内容是：{first_notification_information}')
                # 存入通知表中，记录通知的类型、数量和对象等内容,通知的时间是notify_time
                for notify_info in first_notification_information:
                    insert_sql = '''INSERT INTO `twitter_notification`(`Account_id`,`Platform`,`Notify_Time`,`Notify_Type`,`Comment_Content`,`Comment_URL`,`Actor_URL`,`Original_Note_URL`,`Original_Content`,`Update_Time`) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s);'''
                    self.database.operation(insert_sql,(account_id,'twitter',notify_time,notify_info['notify_type'],notify_info['content'],notify_info['note_url'],notify_info['actors_url'][0],notify_info['original_url'],notify_info['original_content'],datetime.now()))
                    self.log.info(f'{notify_info} 已更新到数据库twitter通知表')
                notify_informations.extend(first_notification_information)   

            self.log.info(f'点击返回按钮')
            self.driver.search_and_click(XPATH='//div[@class="css-175oi2r r-1pz39u2 r-1777fci r-15ysp7h r-1habvwh r-s8bhmr"]/button',waiting_time=5.0) # 点击返回按钮
            temp_time = notify_time  # 记录上一个的时间
            time_flag = False  # 标志位
            while True:
                div_element = self.driver.find_xpath(XPATH='//div[@aria-label="Timeline: Notifications"]')
                article = div_element.find_element(By.XPATH,'//div[@class="css-175oi2r" and @data-testid="cellInnerDiv" and .//article]') # 获取第一个通知
                # 找到第一个，获取第一个的时间
                notify_time = article.find_element(By.TAG_NAME,'time').get_attribute('datetime')   # 第一个通知的时间 str
                # 转换成datetime类型
                notify_time = await self.covert_ustime_to_china(notify_time)
                # 比较当前通知的时间和上一个通知时间，以及当前通知的时间和开始通知时间
                while True:
                    # self.log.info(f'临时时间是：{temp_time}')
                    if notify_time >= temp_time: # 找比temp_time时间小的通知
                        try:
                            article = article.find_element(By.XPATH,'following-sibling::div[@class="css-175oi2r" and @data-testid="cellInnerDiv" and .//article]')
                            self.driver.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", article)
                            await asyncio.sleep(1)
                            notify_time = article.find_element(By.TAG_NAME,'time').get_attribute('datetime')   # 下一个通知的时间
                            # 转换成datetime类型
                            notify_time = await self.covert_ustime_to_china(notify_time)
                            continue
                        except Exception as e:
                            self.log.info(f'所有的通知已经获取完毕')
                            return create_response(create_time=create_time,code=HTTPStatus.OK,message='success',response=notify_informations)
                        # 比较 notify_time  和  temp_time
                    if notify_time < notification_start_time:
                        self.log.info(f'时间不符合{time_limit}')
                        time_flag = True
                        break
                    break

                # 如果当前的时间小于等于通知开始时间，则break掉外循环
                if time_flag: 
                    break

                # 获取内容，然后点击返回按钮
                notification_inforamtion = await self.get_notifications_details(account_id=account_id,article=article)
                if len(notification_inforamtion) == 0:
                    self.log.info(f'此通知是 用户关注/广告')
                else: 
                    self.log.info(f'获取到的通知内容是：{notification_inforamtion}')
                    # 存入数据库或者文件
                    # 存入数据库中曝光表中，记录通知的类型、时间、数量等内容，通知的时间是notify_time
                    for notify_info in first_notification_information:
                        insert_sql = '''INSERT INTO `twitter_notification`(`Account_id`,`Platform`,`Notify_Time`,`Notify_Type`,`Comment_Content`,`Comment_URL`,`Actor_URL`,`Original_Note_URL`,`Original_Content`,`Update_Time`) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s);'''
                        self.database.operation(insert_sql,(account_id,'twitter',notify_time,notify_info['notify_type'],notify_info['content'],notify_info['note_url'],notify_info['actors_url'][0],notify_info['original_url'],notify_info['original_content'],datetime.now()))
                        self.log.info(f'{notify_info} 已更新到数据库twitter通知表')
                    notify_informations.extend(notification_inforamtion)   
                self.log.info(f'点击返回按钮')
                self.driver.search_and_click(XPATH='//div[@class="css-175oi2r r-1pz39u2 r-1777fci r-15ysp7h r-1habvwh r-s8bhmr"]/button',waiting_time=5.0)  # 点击返回按钮
                temp_time  = notify_time
                # 再获取第一个元素，再循环 

                
            # 将查看通知的动作更新到交互表中
            insert_sql = '''INSERT INTO `twitter_interaction`(`Account_id`,`Platform`,`Action`,`Interaction_time`,`Result_list`,`Update_time`) VALUES(%s,%s,%s,%s,%s,%s);'''
            self.database.operation(insert_sql,(account_id,'twitter','查看通知',action_time,str(notify_informations),datetime.now()))
            self.log.info(f'查看通知 已更新到数据库twitter互动表')
            return create_response(create_time=create_time,code=HTTPStatus.OK,message='success',response=notify_informations)

        except Exception as e:
            self.log.error(f'获取通知信息失败，失败原因是：{e}')
            return create_response(create_time=create_time,code=HTTPStatus.BAD_REQUEST,message='error',response=f'获取通知信息失败,原因是：{e}')


    async def get_one_keyword_content(self,account_id,keyword:str=None,article=None):
        '''获取一个贴文的内容 不关闭窗口，然后返回。'''
        create_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            
            if 'https://x.com' not in self.driver.driver.current_url:
                await self.login_by_cookies(account_id=account_id)
    
            url = f'''https://twitter.com/search?q="{keyword}"&src=typed_query&f=live'''  # 选择 Latest
            # 重定向网址
            final1 = requests.get(self.driver.driver.current_url, allow_redirects=True).url
            final2 = requests.get(url, allow_redirects=True).url

            if final1 != final2:
                self.log.info(f'进入网页：{url}')   
                self.driver.get(url=url)
                time.sleep(random.uniform(10,30))

            # article 元素是否存在
            if not article:
                try:
                    article = self.driver.find_xpath(XPATH='//div[@class="css-175oi2r" and @data-testid="cellInnerDiv" and .//article]')
                except:
                    self.log.info(f'未找到任何的相关内容，返回')
                    return {},None
            else:
                article = article.find_element(By.XPATH,'following-sibling::div[@class="css-175oi2r" and @data-testid="cellInnerDiv" and .//article]')

            self.driver.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", article)
            time.sleep(random.uniform(2,4))

            article_url = article.find_element(By.XPATH,'.//a[contains(@class,"css-146c3p1 r-bcqeeo r-1ttztb7 r-qvutc0 ") and contains(@href,"/status/")]').get_attribute("href")
        
            # try:
            #     article.find_element(By.XPATH,'.//div[contains(text(),"Replying to ")]')
            #     self.log.info(f'该推文是用户的评论内容')
            #     tweet_type = "replying"
            # except:
            #     tweet_type = ''
            #     pass   
            self.log.info(f'打开帖子：{article_url} 获取具体的贴文内容')
            self.driver.open_new_tab(url=article_url)
            time.sleep(random.uniform(10,15))
            self.driver.swith_to_new_window(id=-1)
            data = await self.get_one_content()
            data["keyword"] = keyword
            # data['tweet_type'] = tweet_type
            self.log.info(f'搜索热搜词{keyword}获取的曝光内容是:{data}')

            # 添加到曝光表中
            insert_sql = '''INSERT INTO `twitter_records`(`Account_id`,`Platform`,`URL`,`Source_account`,`Content`,`Likes_Num`,`Transmits_Num`,`Views_Num`,`Bookmarks_Num`,`Comments_Num`,`Published_Time_IP`,`Type`,`Form`,`Images_URL`,`Update_time`) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s);'''
            self.database.operation(insert_sql,(account_id,'twitter',data["note_url"],data["nickname"],data["content"],data["likes"],data["transmits"],data["views"],data["bookmarks"],data["comments"],data["post_time_ip"],data["note_type"],data["note_form"],str(data["images_url"]),datetime.now()))
            self.log.info('已更新twitter内容曝光表')

            return  data,article

        except Exception as e:
            self.log.error(f'获取关键词内容失败，失败原因是：{e}')
            return {},None
        
# 建立一个数据表 ，存档跟踪回复的结果

    async def close_now_windows(self):
        await asyncio.sleep(random.uniform(1,4))
        self.driver.close()
        await asyncio.sleep(random.uniform(2,5))
        self.driver.swith_to_new_window(id=-1)
        await asyncio.sleep(random.uniform(2,5))




            