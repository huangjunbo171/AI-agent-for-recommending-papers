
import os
import sys
pythonpath = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0,pythonpath)
import time
from base_bot.base_bot import WebDriver
import os
from base_bot.email_bot import WangyiBot
import re
import asyncio
from utils.log import logger
import pdb
import ast
from urllib.parse import urljoin
from selenium.webdriver.common.action_chains import ActionChains
# usage有 reply_comment comment transmit post
# 衍生的附加属性 post_content comment_content
from bs4 import BeautifulSoup
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
import threading
import random 
from utils.sql import sql_dataset
import json
from utils.generation  import *
from datetime import datetime, timedelta
# from generation import generation_post,generation_comment
import pyperclip
from http import HTTPStatus
from xhs_agent.xhs_request import create_response
from utils.interests import get_character, interest_detection
import re
from utils.prompt import *
from zoneinfo import ZoneInfo
class XiaohongshuBot():
    def __init__(self, log_path: str = "./logs/xhs/xhs_log.log",ip=None,username=None,password=None,headless=False):
        """
        初始化xiaohongshuBot类的实例。

        参数：
        - log_path：日志文件路径，默认为 father_directory/logs/xiaohongshu/xiaohongshu_log.log

        返回值：
        无
        """
        super().__init__()
        self.driver = WebDriver(log_path=log_path,ip=ip,username=username,password=password,headless=headless)
        self.log = logger(filename=log_path)
        self.database = sql_dataset('xiaohongshu')

    
    async def login_by_phone(self,phone:str,email_account:str='13205412656',email_password:str='1q2w3e4r@'):
        '''通过账号和验证码登录'''
        create_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            # pdb.set_trace()
            # 查询数据库，如果没有该手机号，则插入数据
            select_sql = f'''SELECT Id FROM accounts_info WHERE Phone = {phone}'''
            result = self.database.get_dict_data_sql(select_sql)
            if not result:
                insert_sql = "INSERT INTO `accounts_info` (`Platform`,`Phone`) VALUES (%s,%s)"
                self.database.operation(insert_sql,('小红书',phone))
            account_id = self.database.get_dict_data_sql(select_sql)[0]["Id"]
            self.log.info('进入小红书官网')
            self.driver.get(url='https://www.xiaohongshu.com')
            time.sleep(10)
            action_time = datetime.now()
            self.log.info("点击输入小红书手机号")
            self.driver.search_and_click(XPATH="//input[@placeholder='输入手机号']", waiting_time=1.0)
            self.driver.send_content(XPATH="//input[@placeholder='输入手机号']", content = phone)
            time.sleep(2)
            self.log.info("点击小红书获取验证码按键")
            self.driver.search_and_click(XPATH="//span[text()='获取验证码']", waiting_time=1.0)
            time.sleep(2)
            # 获取验证码
            code = self.get_verify_code(email_account=email_account,email_passwd=email_password)
            self.log.info(f"获取验证码:{code}")
            self.log.info("输入小红书验证码")
            self.driver.search_and_click(XPATH="//input[@placeholder='输入验证码']", waiting_time=1.0)
            self.driver.send_content(XPATH="//input[@placeholder='输入验证码']", content = code)
            time.sleep(2)
            self.log.info("点击小红书阅读同意协议")
            self.driver.search_and_click(XPATH="//span[@class='agree-icon']", waiting_time=1.0)
            time.sleep(0.2)
            self.log.info("点击小红书登录")
            self.driver.search_and_click(XPATH="//button[@class='submit active']", waiting_time=1.0)
            time.sleep(2)
            new_cookies = json.dumps(self.driver.get_cookies(url="https://www.xiaohongshu.com"))
            self.log.info("获取新cookies")
            # 获取账号主页
            profile = self.driver.find_xpath(XPATH='//li[@class="user side-bar-component"]').find_element(By.TAG_NAME,'a').get_attribute("href")
            sql = '''UPDATE accounts_info SET Cookie = %s, Cookie_status = %s, URL = %s, Platform = %s,Latest_login_time = %s WHERE Phone = %s;'''
            self.database.operation(sql,(new_cookies,'在线',profile,'小红书',datetime.now(),phone))
            time.sleep(3)
            self.log.info("更新数据库cookies成功")
            # 添加到互动表，
            now_time = datetime.now()
            insert_sql = '''INSERT INTO `xiaohongshu_interaction`(`Account_id`,`Platform`,`Action`,`URL`,`Update_time`) VALUES(%s,%s,%s,%s,%s,%s);'''
            self.database.operation(insert_sql,(account_id,'小红书','登录',profile,action_time,now_time))
            self.log.info('登录 已更新到数据库小红书互动表')
            await self.get_user_profile(account_id=account_id)
            self.log.info(f'手机号{phone}登录小红书成功')
            # return {"status": "success", "message": f"利用手机号{phone}登录成功","response":f"利用手机号{phone}登录成功"}
            return create_response(create_time=create_time,code=HTTPStatus.OK,message='success',response=f'利用手机号{phone}登录成功')
        except Exception as e:
            self.log.error(f'手机号{phone}登录小红书失败:原因是{e}')
            return create_response(create_time=create_time,code=HTTPStatus.BAD_REQUEST,message='error',response=f'利用手机号{phone}登录失败')

    
    
    def get_verify_code(self,email_account,email_passwd):
        "获取验证码"
        try:
            # pdb.set_trace()
            emailbot = WangyiBot()
            code = emailbot.get_verify_code(account=email_account,password=email_passwd)  
            emailbot.driver.quit()
            return code
        except Exception as e:
            self.log.error(f"获取验证码失败，原因是：{e}")
            return 


    def get_qrcode_url(self,account_id):
        '''进入小红书官网,获取二维码链接，有效时长：5分钟'''
        try:
            self.log.info(f'账号{account_id}尝试扫码登录')
            self.driver.get(url='https://www.xiaohongshu.com')
            time.sleep(10)
            try:
                self.driver.find_xpath(XPATH='//div[@class="login-container"]')
                self.log.info('存在登录面板，获取二维码链接')
            except:
                self.log.info('不存在登录面板，点击登录按钮,获取二维码链接')
                self.driver.search_and_click(XPATH='//button[@id="login-btn"]',waiting_time=5.0)
            # 获取二维码链接
            qrcode_url = self.driver.find_xpath(XPATH='//img[@class="qrcode-img"]').get_attribute("src")
            # 存入数据库
            sql = '''UPDATE accounts_info SET QRcode_url = %s WHERE Account_id = %s;'''
            self.database.operation(sql,(qrcode_url,account_id))
            self.log.info(f"账号{account_id}的登录二维码链接已保存到数据库")
            return {"status": "success", "message": f"获取账号{account_id}登录二维码成功","response":f"获取账号{account_id}登录二维码成功"}
        except Exception as e:
            return {"status": "error", "message": f"获取账号{account_id}登录二维码失败","response":f"原因是：{e}"}
     
     
      
    def refresh_qrcode(self,account_id):
        '''刷新二维码'''
        try:
            self.get_qrcode_url(account_id=account_id)
            return f'账号{account_id}抖音刷新二维码成功'
        except Exception as e:
            self.log.error(f'刷新二维码失败，原因是：{e}') 
            return f'账号{account_id}抖音刷新二维码失败'   
        
        
                
    async def login_by_cookies(self,account_id):
        '''使用cookies登录账号'''
        create_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            # 从数据库中查询账号信息
            search_sql = f"SELECT * FROM accounts_info WHERE accounts_info.Account_id = {account_id}"
            result = self.database.get_dict_data_sql(search_sql)[0]
            self.log.info("从数据库中获取到的账号信息:{}".format(result))
            profile = result['URL']  # 主页链接
            cookies = result['Cookie'] # cookies
        except Exception as e:
            self.log.error("获取账号信息失败，原因：{}".format(e))
            # raise Exception("获取账号信息失败") 
            return create_response(create_time=create_time,code=HTTPStatus.BAD_REQUEST,message='error',response=f'账号{account_id}cookies下线，利用cookies登录失败')
        try:
            action_time = datetime.now()
            # 利用cookie登录
            cookies = json.loads(cookies)
            self.driver._login(url = 'https://www.xiaohongshu.com',cookies=cookies)
            time.sleep(10)     
            # 检查是否登录成功，账号链接是否和数据库中的一样
            href = self.driver.find_xpath(XPATH='//li[@class="user side-bar-component"]//a[@class="link-wrapper"]').get_attribute("href")
            time.sleep(1)
            if profile != '' and href != profile:
                self.log.info(f"数据库中的主页链接为{profile}，当前的主页链接为{href}，不一致")
                sql = '''UPDATE accounts_info SET Cookie_status = %s WHERE Account_id = %s;'''
                self.database.operation(sql,('下线',account_id))
                time.sleep(3)
                self.log.error(f'账号{account_id}cookies下线，利用cookies登录失败')
                # raise ValueError  # 抛出异常
                return create_response(create_time=create_time,code=HTTPStatus.BAD_REQUEST,message='error',response=f'账号{account_id}cookies下线，利用cookies登录失败')
            else:
                self.log.info("利用cookies登录成功")
            # 修改账号信息表的最近登录时间
            sql = '''UPDATE accounts_info SET Latest_login_time = %s WHERE Account_id = %s;'''
            self.database.operation(sql,(datetime.now(),account_id))
            time.sleep(2)
            # 添加到互动表，
            insert_sql = '''INSERT INTO `xiaohongshu_interaction`(`Account_id`,`Platform`,`Action`,`URL`,`Interaction_time`,`Update_time`) VALUES(%s,%s,%s,%s,%s,%s);'''
            self.database.operation(insert_sql,(account_id,'小红书','登录',href,action_time,datetime.now()))
            self.log.info('登录 已更新到数据库小红书互动表')
            await self.get_user_profile(account_id=account_id)
            return create_response(create_time=create_time,code=HTTPStatus.OK,message='success',response=f'账号{account_id}cookies登录成功')    
        except Exception as e:
            sql = '''UPDATE accounts_info SET Cookie_status = %s WHERE Account_id = %s;'''
            self.database.operation(sql,('下线',account_id))
            time.sleep(3)
            self.log.error(f'账号{account_id}cookies下线，利用cookies登录失败')
            return create_response(create_time=create_time,code=HTTPStatus.BAD_REQUEST,message='error',response=f'账号{account_id}cookies下线，利用cookies登录失败')
      
        
    async def login_by_qrcode(self,account_id=None):
        '''二维码扫码登录账号account_id'''
        try: # 登录成功则更新cookie
            # create_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            time.sleep(3)
            action_time = datetime.now()
            current_url = self.driver.driver.current_url
            self.log.info(f"当前网页链接为：{current_url}")
            if current_url != 'https://www.xiaohongshu.com/explore':
                self.log.info(f'小红书账号{account_id}扫码登录失败')
                return f'小红书账号{account_id}扫码登录失败'
            # 检查是否登录成功，是否包含主页链接是否一致
            # pdb.set_trace()
            self.driver.search_and_click(XPATH='//li[@class="user side-bar-component"]//a[@class="link-wrapper"]',waiting_time=3.0)
            profile = self.driver.driver.current_url
            data = self.database.get_dict_data_sql(f"SELECT * FROM accounts_info WHERE accounts_info.URL = '{profile}'")
            if data and data[0]['Account_id']!=account_id:
                self.log.info(f"输入账号为{account_id}与扫描账号{data[0]['Id']}不匹配，请检查后重新登录")
                return f"输入账号为{account_id}与扫描账号{data[0]['Id']}不匹配，请检查后重新登录"
                # return create_response(create_time=create_time,code=HTTPStatus.BAD_REQUEST,message='error',response=f"输入账号为{account_id}与扫描账号{data[0]['Account_id']}不匹配，请检查后重新登录")
            # 更新cookies和账号的url,nickname
            time.sleep(3)
            new_cookies = json.dumps(self.driver.get_cookies(url="https://www.xiaohongshu.com"))
            self.log.info("获取新cookies")
            sql = '''UPDATE accounts_info SET Cookie = %s, Cookie_status = %s, URL = %s, Platform = %s,First_login_time=%s WHERE Account_id = %s;'''
            self.database.operation(sql,(new_cookies,'在线',profile,'小红书',datetime.now(),account_id))
            time.sleep(3)
            self.log.info("更新数据库cookies成功")
            self.log.info(f'小红书账号{account_id}扫码登录成功')
            # 添加到互动表
            insert_sql = '''INSERT INTO `xiaohongshu_interaction`(`Account_id`,`Platform`,`Action`,`URL`,`Interaction_time`,`Update_time`) VALUES(%s,%s,%s,%s,%s,%s);'''
            self.database.operation(insert_sql,(account_id,'小红书','登录',profile,action_time,datetime.now()))
            self.log.info('登录 已更新到数据库小红书互动表')
            # 获取账号的主页信息
            await self.get_user_profile(account_id=account_id)
            return f'账号{account_id}小红书扫码登录成功'
            # return create_response(create_time=create_time,code=HTTPStatus.OK,message='success',response=f'账号{account_id}小红书扫码登录成功')
        except Exception as e:
            self.log.error("更新数据库cookies失败，原因：{}".format(e))
            return f'账号{account_id}小红书扫码登录失败'
            # return create_response(create_time=create_time,code=HTTPStatus.BAD_REQUEST,message='error',response=f'账号{account_id}小红书扫码登录失败')
      
      
         
    async def get_user_profile(self,account_id):
        try:
            create_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if 'https://www.xiaohongshu.com/' not in self.driver.driver.current_url:
                self.log.info(f'登录账号{account_id}')
                await self.login_by_cookies(account_id=account_id)
            # 获取用户信息
            sql = f"SELECT URL FROM accounts_info WHERE accounts_info.Account_id = {account_id};"
            url = self.database.get_dict_data_sql(sql)[0]['URL']
            self.log.info("获取个人中心获取用户信息")
            self.driver.get(url)
            time.sleep(5)
            nickname = self.driver.find_xpath(XPATH='//div[@class="user-name"]').text
            redid = self.driver.find_xpath(XPATH='//span[@class="user-redId"]').text.replace('小红书号：','')
            try:
                redip = self.driver.find_xpath(XPATH='//span[@class="user-IP"]').text.replace('IP属地：','')
            except:
                redip = ''
            interaction = self.driver.find_xpath(XPATH='//div[@class="user-interactions"]')
            interaction_list =interaction.find_elements(By.XPATH,'.//span[@class="count"]')
            follows = interaction_list[0].text
            fans = interaction_list[1].text
            collects_likes = interaction_list[2].text
            try:
                brief = self.driver.find_xpath(XPATH='//div[@class="user-desc"]').text
            except:
                brief = ''
            data = {"账号昵称":nickname,"小红书id":redid,"粉丝数":fans,"关注数":follows,"获赞与收藏量":collects_likes,"IP属地":redip,"简介":brief}
            self.log.info(f'获取到的用户主页信息是：{data}')
            # 更新属性表
            result = self.database.get_dict_data_sql(sql=f"SELECT * FROM social_attributes WHERE Account_id = '{account_id}'")
            if not result:
                insert_sql = '''INSERT INTO `social_attributes`(`Account_id`,`Platform`) VALUES(%s,%s);'''
                self.database.operation(insert_sql,(account_id,'小红书'))
            sql = '''UPDATE social_attributes SET Nickname = %s, Fans_num = %s, Follows_num = %s, Likes_num = %s,Red_ip = %s,Red_id = %s,Brief = %s,Update_time = %s WHERE Account_id = %s;'''
            self.database.operation(sql,(nickname,fans,follows,collects_likes,redip,redid,brief,datetime.now(),account_id))
            self.log.info(f'账号{account_id}的用户信息已保存到数据库')
            return create_response(create_time=create_time,code=HTTPStatus.OK,message='success',response=data)
        except Exception as e:
            self.log.error(f'获取账号{account_id}用户信息失败:{e}')
            return create_response(create_time=create_time,code=HTTPStatus.BAD_REQUEST,message='error',response=f'账号{account_id}获取主页信息失败')
    
    
    
    # async def scroll(self,account_id,url=None,duration=None):
    #     '''在网页url滑动duration时长，默认是在首页滑动10s'''
    #     try:
    #         self.log.info(f'登录账号{account_id}')
    #         await self.login_by_cookies(account_id=account_id)
    #         # pdb.set_trace()
    #         if url:
    #             self.driver.get(url=url)
    #             time.sleep(5)
    #             action_time = datetime.now()
    #             note_element = self.driver.find_xpath(XPATH='//div[@class="note-scroller"]')
    #             start_time = time.time()  # 记录开始时间
    #             while time.time() - start_time < duration:
    #                 self.driver.driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight;", note_element)
    #                 time.sleep(random.randint(1,2))
    #         else:
    #             action_time = datetime.now()
    #             self.log.info(f'默认在首页滑动{duration}')
    #             start_time = time.time()  # 记录开始时间
    #             while time.time() - start_time < duration:
    #                 self.driver.scroll(size=200) 
    #                 time.sleep(random.randint(1,2)) 
    #         # 添加到互动表，
    #         now_time = datetime.now()
    #         insert_sql = '''INSERT INTO `xiaohongshu_interaction`(`Account_id`,`Platform`,`Content`,`Type`,`Action`,`URL`,`Interaction_time`,`Result_list`,`Update_time`) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s);'''
    #         self.database.operation(insert_sql,(account_id,'小红书',None,None,'浏览',url,action_time,None,now_time))
    #         self.log.info('浏览 已更新到数据库小红书互动表')
    #         return {"status": "success", "message": f"小红书账号{account_id}浏览推荐页面成功","response":f"小红书账号{account_id}成功地浏览推荐页面{duration}秒"}
    #     except Exception as e:
    #         self.log.error(f'账号{account_id}滑动网页失败')
    #         return {"status": "error", "message": f"账号{account_id}浏览推荐页面失败","response":f"原因是：{e}"}
    
    
    async def get_post_urls(self,account_id,url=None,num=10):
        '''
        账号account_id，获取某作者url主页的num个作品链接，url默认为空，默认爬取account_id账号主页
        '''
        try:
            create_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.log.info(f'登录账号{account_id}')
            await self.login_by_cookies(account_id=account_id)
            if not url:
                self.log.info(f'账号{account_id}开始获取本账号主页的{num}条帖子链接')
                db_url = self.driver.driver.current_url
            if url:
                self.log.info(f'进入作者主页链接：{url}')
                db_url = url
                self.driver.get(url = url)
                time.sleep(10)
                self.log.info(f'账号{account_id}开始获取账号{url}主页的{num}条帖子链接')
            select_num = 0
            stored_urls = set() # 存放不重复帖子链接
            results = [] # 存放最终结果，
            action_time = datetime.now()
            while select_num < num:
                html = self.driver.driver.page_source
                soup = BeautifulSoup(html,'lxml')
                notes = soup.find_all("section",class_="note-item") 
                if len(notes) == 0:
                    self.log.info(f'作者未发布任何笔记')
                    return {"status": "success", "message": f'作者{url}未发布任何笔记','response':f'爬取到的帖子链接是：None'}
                if len(notes) < 21 and len(notes) < num:
                    self.log.info(f'作者共发布{len(notes)}条笔记')
                    num = len(notes)
                for note in notes:
                    try:
                        note_element = note.find('a',class_='cover mask ld')
                        if note_element:
                            continue
                        href = note_element.get("href")
                        full_url = urljoin('https://www.xiaohongshu.com', href) # 完整的链接
                    except AttributeError:
                        self.log.warning("网页结构可能已变化，未找到 note 元素")
                        continue
                    if full_url not in stored_urls:
                        continue
                    data = self.get_one_content(url=full_url)
                    results.append(full_url)
                    select_num += 1
                    stored_urls.add(full_url)
                    # 查询数据库中是否已经有该条数据full_url
                    check_sql = f"SELECT * FROM xiaohongshu_records WHERE URL = '{full_url}'"
                    check_result = self.database.get_dict_data_sql(check_sql)
                    if check_result:
                        self.log.info(f'文章{full_url}已经存在于数据库中，不再继续添加')
                        continue
                    # 不存在于数据库，则添加到曝光表
                    now_time = datetime.now()
                    insert_sql = '''INSERT INTO `xiaohongshu_records`(`Account_id`,`Platform`,`URL`,`Source_nickname`,`Source_redid`,`Title`,`Content`,`Likes_Num`,`Collects_Num`,`Comments_Num`,`Published_Time_IP`,`Type`,`Form`,`Images_URL`,`Update_time`) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s);'''
                    self.database.operation(insert_sql,(account_id,'小红书',full_url,data["nickname"],data["redid"],data["title"],data["content"],data["likes_num"],data["collects_num"],data["comments_num"],data["post_time_ip"],data["note_type"],data["note_form"],str(data["images_url"]),now_time))   
                    self.log.info('已更新小红书内容曝光表')
                    # 添加到互动表，
                    content = (data.get("title") or "") + (data.get("content") or "")
                    insert_sql = '''INSERT INTO `xiaohongshu_interaction`(`Account_id`,`Platform`,`Content`,`Type`,`Action`,`URL`,`Interaction_time`,`Result_list`,`Update_time`) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s);'''
                    self.database.operation(insert_sql,(account_id,'小红书',content,data["note_type"],'检索',str(full_url),action_time,None,now_time))
                    self.log.info('检索 已更新到数据库小红书互动表') 
                self.driver.scroll(size=200)
            self.log.info(f'账号{account_id}获取主页{db_url}的{num}条帖子链接成功,并已存到数据库中,帖子链接是：{results}')
            return create_response(create_time=create_time,code=HTTPStatus.OK,message='success',response=results) 
        except Exception as e:
            self.log.error(f'账号{account_id}获取主页{db_url}的{num}条帖子链接失败,原因是：{e}')
            return create_response(create_time=create_time,code=HTTPStatus.BAD_REQUEST,message='error',response=f'账号{account_id}获取主页{db_url}的{num}条帖子链接失败') 
    
        
    async def posts(self, account_id,  file_paths=None, title=None, content=None, tags=None,usage:str='picture'):
        '''
        小红书发布笔记

        参数：
            -usage:video/picture，发布视频/图文笔记
            -file_paths：图片/视频路径,列表形式，循环上传
            -topic: 笔记标题
            -content：笔记内容
        '''
        try:
            create_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            # 先进入首页
            self.driver.get(url =  'https://www.xiaohongshu.com')
            time.sleep(random.uniform(5,10))
            # 检查如果当前账号没有登录成功，则登录
            # try:
            #     href = self.database.get_dict_data_sql(sql=f'SELECT  * FROM accounts_info WHERE Account_id = {account_id}')[0]['URL']
            #     if href == self.driver.find_xpath(XPATH='//div[@class="active router-link-exact-active link-wrapper" and contains(@href,"/user/profile")]').get_attribute('href'):
            #         self.log.info(f'账号{account_id}登录正常')
            #     else:
            #         self.log.info(f'登录账号{account_id}')
            #         await self.login_by_cookies(account_id=account_id)
            # except:
            #     self.log.info(f'登录账号{account_id}')
            #     await self.login_by_cookies(account_id=account_id)

            if 'https://www.xiaohongshu.com/' not in self.driver.driver.current_url:
                await self.login_by_cookies(account_id=account_id)

            if isinstance(tags,str):
                tags = [tags]
            if len(content)>1000:
                content = content[:1000]   # 直接截断
            # 过滤掉超出BMP范围的字符
            content = ''.join(c for c in content if ord(c) <= 0xFFFF) 
            content = content.replace('*','')
            if isinstance(file_paths,str):
                file_paths = [file_paths]
            file_paths = [os.path.abspath(path) for path in file_paths]  # 转换成绝对路径
            # self.log.info("进入小红书首页")
            # self.driver.get(url='https://www.xiaohongshu.com/explore')
            # time.sleep(10)
            pdb.set_trace()
            self.log.info("进入创作者首页，点击发布按钮")
            ul_element = self.driver.find_xpath(XPATH='//ul[@class="channel-list"]')
            a_element = ul_element.find_element(By.XPATH,'.//a[@target="_blank"]')
            self.driver.get(url=a_element.get_attribute("href"))
            # self.driver.get(url = "https://creator.xiaohongshu.com/publish/publish?source=official")
            time.sleep(random.uniform(10,20))
            self.log.info(f'点击 发布笔记 按钮')
            self.driver.search_and_click(XPATH='//div[@class="publish-video"]',waiting_time=random.uniform(2,5))
            if usage == "video":
                # note_type = '视频'
                self.log.info("点击小红书上传视频按钮")
                self.driver.search_and_click(XPATH="//span[text()='上传视频']", waiting_time=1.0)
                time.sleep(1)
                self.log.info("上传小红书视频")
                self.driver.send_content(XPATH="//input[@class='upload-input']", content='\n'.join(file_paths))
                time.sleep(1)
            elif usage == "picture":
                self.log.info("点击小红书上传图文按钮")
                self.driver.find_xpaths(XPATH="//span[text()='上传图文']")[-1].click()
                time.sleep(random.uniform(2,5))
                self.log.info("上传小红书图片")
                self.driver.send_content(XPATH='//input[@type="file"]',content='\n'.join(file_paths))
                time.sleep(random.uniform(4,10))
            
            # 输入具体的笔记内容
            if title: 
                self.log.info("点击小红书标题输入框")
                self.driver.search_and_click(XPATH='//input[@placeholder="填写标题会有更多赞哦～"]', waiting_time=1.0)
                self.driver.send_content(XPATH='//input[@placeholder="填写标题会有更多赞哦～"]', content = title)
                time.sleep(2)
            if content:
                self.log.info("点击小红书内容输入框")
                self.driver.search_and_click(XPATH='//div[@class="tiptap ProseMirror"]', waiting_time=random.uniform(1,3))
                self.driver.send_content(XPATH='//div[@class="tiptap ProseMirror ProseMirror-focused"]', content = content)
                time.sleep(random.uniform(4,10))
            
            if tags:
                # 添加话题
                self.log.info("点击小红书添加话题按钮")
                for tag in tags:
                    self.driver.search_and_click(XPATH="//button[@id='topicBtn' and @class='contentBtn']", waiting_time=random.uniform(1,3))
                    self.log.info(f"小红书添加话题:{tag}")
                    self.driver.send_content(XPATH='//div[@class="tiptap ProseMirror ProseMirror-focused"]',content=tag)
                    time.sleep(random.uniform(2,5))
                    self.driver.send_content(XPATH='//div[@class="tiptap ProseMirror ProseMirror-focused"]',content='  ')
                    time.sleep(random.uniform(0.5,2))
                    try:
                        self.driver.search_and_click(XPATH='//div[@class="item is-selected"]/span[1]',waiting_time=2.0)  # 选的是第一个tag
                        # self.driver.search_and_click(XPATH='//div[@id="creator-editor-topic-container"]/div[1]',waiting_time=2.0)
                    except:
                        pass
            action_time = datetime.now()
            self.log.info("点击小红书发布按钮")
            self.driver.search_and_click(XPATH='//button[contains(@class,"publishBtn")]', waiting_time=5.0)
            self.log.info("小红书帖子发布成功")
            time.sleep(random.uniform(15,40))  # 等待10s
            content_url = self.get_content_url(account_id=account_id)
            self.log.info(f'获取发布成功帖子的链接:{content_url}')
            # 添加到互动表，
            if content_url:
                # 添加到交互表中
                note_type = '原创'
                title_content = (title or "") + (content or "")
                post_result = str([{content_url :title_content}]) 
                insert_sql = '''INSERT INTO `xiaohongshu_interaction`(`Account_id`,`Platform`,`Content`,`Type`,`Action`,`URL`,`Interaction_time`,`Result_list`,`Update_time`) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s);'''
                self.database.operation(insert_sql,(account_id,'小红书',title_content,note_type,'发帖',post_result,action_time,None,datetime.now()))
                self.log.info(f'发帖 已更新到数据库小红书互动表')
                return create_response(create_time=create_time,code=HTTPStatus.OK,message='success',response=content_url)  
            else:
                self.log.error(f'账号{account_id}小红书内容发布失败，未获得有效作品链接') 
                return create_response(create_time=create_time,code=HTTPStatus.BAD_REQUEST,message='error',response=f'账号{account_id}发布失败')  
        except Exception as e:
            self.log.error(f'账号{account_id}小红书内容发布失败，原因是：{e}') 
            return create_response(create_time=create_time,code=HTTPStatus.BAD_REQUEST,message='error',response=f'账号{account_id}发布失败') 
    


    def get_content_url(self,account_id=None):
        '''获取刚发布作品的链接'''
        try:
            # pdb.set_trace()
            search_sql = f"SELECT * FROM accounts_info WHERE accounts_info.Account_id = '{account_id}'"
            result = self.database.get_dict_data_sql(search_sql)
            account_url = result[0]['URL']
            self.log.info(f'进入小红书账号{account_id}主页:{account_url}')
            self.driver.get(url = account_url )
            time.sleep(random.uniform(10,20))
            # 第一个小红书帖子
            first_article_element = self.driver.find_xpath(XPATH='//section[@class="note-item"]')  #  note-item
            content_url = first_article_element.find_element(By.XPATH,'.//a[@class="cover mask ld"]').get_attribute("href")
            # 拼接完整
            # content_url = urljoin('https://www.xiaohongshu.com',content_url)
            self.log.info(f'获取账号{account_id}的帖子链接成功，链接是：{content_url}')
            return content_url     
        except Exception as e:
            self.log.error(f'获取小红书账号{account_id}发布的帖子链接失败，原因是：{e}')
            return None


    async def comments(self,account_id,url, content,post_data:dict=None,file_paths:list=None):
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
            if 'https://www.xiaohongshu.com/' not in self.driver.driver.current_url:
                await self.login_by_cookies(account_id=account_id)
            if self.driver.driver.current_url != url:
                self.log.info(f'进入网页：{url}')
                self.driver.get(url)
                await asyncio.sleep(random.uniform(10,15))

            action_time = datetime.now()
            self.log.info(f'点击评论框，输入评论内容:{content}')
            self.driver.search_and_click(XPATH='//div[@class="content-edit"]', waiting_time=1.0)
            self.driver.send_content(XPATH="//p[@id='content-textarea']", content = content)
            time.sleep(2)
            self.log.info('点击发送按钮')
            self.driver.search_and_click(XPATH="//button[@class='btn submit']", waiting_time=3.0)
            self.log.info("小红书评论成功")
            if not post_data:
                data = await self.get_one_content()
            else:
                data = post_data
            # 添加到互动表，
            now_time = datetime.now()
            post_content = (data.get("title") or "") + (data.get("content") or "")
            insert_sql = '''INSERT INTO `xiaohongshu_interaction`(`Account_id`,`Platform`,`Content`,`Type`,`Action`,`URL`,`Interaction_time`,`Result_list`,`Update_time`) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s);'''
            self.database.operation(insert_sql,(account_id,'小红书',post_content,data["note_type"],'评论',url,action_time,content,now_time))
            self.log.info('评论 已更新到数据库小红书互动表')
            return create_response(create_time=create_time,code=HTTPStatus.OK,message='success',response=f'账号{account_id}评论成功')
        except Exception as e:
            self.log.error(f"账号{account_id}评论失败，原因：{e}")
            return create_response(create_time=create_time,code=HTTPStatus.BAD_REQUEST,message='error',response=f'账号{account_id}评论失败')


    # 点赞指定帖子/视频
    async def likes(self, account_id, url,post_data:dict=None):
        '''
        参数：
            -account_id:账号id
            -url：指定帖子/视频的链接
        返回：None
        '''
        try:
            create_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if 'https://www.xiaohongshu.com/' not in self.driver.driver.current_url:
                await self.login_by_cookies(account_id=account_id)
            if self.driver.driver.current_url != url:
                self.log.info(f'进入网页：{url}')
                self.driver.get(url)
                await asyncio.sleep(random.uniform(10,15))
            self.log.info('点击点赞按钮')
            action_time = datetime.now()
            self.driver.search_and_click(XPATH='//*[@id="noteContainer"]/div[4]/div[3]/div/div/div[1]/div[2]/div/div[1]/span[1]',waiting_time=3.0)
            self.log.info("小红书点赞成功")
            if not post_data:
                data = await self.get_one_content()
            else:
                data = post_data
            # 添加到互动表，
            now_time = datetime.now()
            post_content = (data.get("title") or "") + (data.get("content") or "")
            insert_sql = '''INSERT INTO `xiaohongshu_interaction`(`Account_id`,`Platform`,`Content`,`Type`,`Action`,`URL`,`Interaction_time`,`Result_list`,`Update_time`) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s);'''
            self.database.operation(insert_sql,(account_id,'小红书',post_content,data["note_type"],'点赞',url,action_time,None,now_time))
            self.log.info('点赞 已更新到数据库小红书互动表')
            return create_response(create_time=create_time,code=HTTPStatus.OK,message='success',response=f'账号{account_id}点赞成功')
        except Exception as e:
            self.log.error(f"账号{account_id}点赞失败，原因：{e}")
            return create_response(create_time=create_time,code=HTTPStatus.BAD_REQUEST,message='error',response=f'账号{account_id}点赞失败')


    # 小红书 收藏
    async def collects(self, account_id,url,post_data:dict=None):
        '''
        参数：
            -account_id:账号id
            -url：指定帖子/视频的链接
        返回：None
        '''
        try:
            create_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if 'https://www.xiaohongshu.com/' not in self.driver.driver.current_url:
                await self.login_by_cookies(account_id=account_id)
            if self.driver.driver.current_url != url:
                self.log.info(f'进入网页：{url}')
                self.driver.get(url)
                await asyncio.sleep(random.uniform(10,15))
            self.log.info('点击收藏按钮')
            action_time = datetime.now()
            self.driver.search_and_click(XPATH='//span[@id="note-page-collect-board-guide"]',waiting_time=2.0)
            self.log.info("小红书收藏成功")
            if not post_data:
                data = await self.get_one_content()
            else:
                data = post_data
            # 添加到互动表，
            now_time = datetime.now()
            post_content = (data.get("title") or "") + (data.get("content") or "")
            insert_sql = '''INSERT INTO `xiaohongshu_interaction`(`Account_id`,`Platform`,`Content`,`Type`,`Action`,`URL`,`Interaction_time`,`Result_list`,`Update_time`) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s);'''
            self.database.operation(insert_sql,(account_id,'小红书',post_content,data["note_type"],'收藏',url,action_time,None,now_time))
            self.log.info('收藏 已更新到数据库小红书互动表')
            return create_response(create_time=create_time,code=HTTPStatus.OK,message='success',response=f'账号{account_id}收藏成功')
        except Exception as e:
            self.log.error(f"账号{account_id}收藏失败，原因：{e}")
            return create_response(create_time=create_time,code=HTTPStatus.BAD_REQUEST,message='error',response=f'账号{account_id}收藏失败')


    # 小红书举报（投诉）帖子/用户
    def complaints(self, account_id,complaint_url:str,class1:str, class2:str=None, reason:str=None,method:str='post'):
        '''
        参数：
            -complaint_url：举报链接
            -class1：举报类型1
            -class2：举报类型2
            -reason：具体的举报原因
            -method: 举报的类型：user/post，默认是post
        输出：None
        '''
        sql = f'''SELECT * FROM social_attributes WHERE Account_id = {account_id}'''
        result = self.database.get_dict_data_sql(sql)[0]
        try:
            search_sql = f'''SELECT * FROM complaint_status WHERE Complaint_url = '{complaint_url}' AND Red_id = '{result["Red_id"]}';'''
            result_list = self.database.get_dict_data_sql(search_sql)
            if result_list:
                self.log.info(f"账号{account_id}已投诉过链接{complaint_url}！")
                return 
        except Exception as e:
            self.log.error(f"数据库查询失败：{e}")
        try:
            
            self.log.info("进入小红书被举报帖子")
            self.driver.get(complaint_url)
            time.sleep(10)
            if self.driver.driver.current_url == 'https://www.xiaohongshu.com/explore?source=404':  
                self.log.error(f'小红书内容{complaint_url}不存在，无法完成本次投诉，已自动跳转到小红书首页')
                insert_sql = '''INSERT INTO `complaint_status`(`Complaint_content`,`Complaint_url`,`Red_id`,`Nickname`,`Complaint_status`) VALUES(%s, %s, %s,%s, %s);'''
                self.database.operation(insert_sql,(None,complaint_url, result["Red_id"],result["Nickname"],'链接内容不存在'))
                    
                return   
            # 获取举报的内容
            
            data = self.get_one_content()
            self.log.info(f'要举报的内容是：{data}')
            # 找到...按钮
            self.driver.search_and_click(XPATH='//div[@class="note-detail-dropdown"]',waiting_time=3.0)  # 展开帖子“举报”的浮框，滑动鼠标点击
        
            # 点击 举报
            self.log.info('点击举报')
            self.driver.search_and_click(XPATH='//span[text()="举报"]')
            time.sleep(3)
            self.log.info(f'选择举报类型: {class1}')
            class1_xpath = f"//div[text()='{class1}']"
            div_class1 = self.driver.find_xpath(XPATH = class1_xpath)
            time.sleep(3)
            # 勾选 举报类型1
            select_div = div_class1.find_element(By.XPATH, "following-sibling::div[@class='no-select']")
            time.sleep(3)
            select_div.click()
            # 点击下一步
            self.driver.search_and_click(XPATH='//div[text()="下一步"]',waiting_time=3.0)
            # 选择class2 和reason
            #3 如果class2和reason都是空的，那就是直接提交，如果均不为空，则选择
            if class2:
                # 选择相应的类型2
                self.log.info(f'选择具体的举报问题:{class2}')
                class2_xpath = f"//div[text()=' {class2}' and @class='choice-item']"
                self.driver.search_and_click(XPATH = class2_xpath,waiting_time=3.0)
            if reason:
                # 填写reason
                self.log.info(f'填写举报描述: {reason}')
                self.driver.search_and_click(XPATH='//textarea[@class="advice-input"]',waiting_time=3.0)
                self.driver.send_content(XPATH='//textarea[@class="advice-input"]',content=reason)
                time.sleep(3)
            
            # 点击提交
            self.log.info('点击提交按钮')
            self.driver.search_and_click(XPATH='//div[text()="提交"]',waiting_time=1.0)
            self.log.info('小红书帖子举报成功！')
            insert_sql = '''INSERT INTO `complaint_status`(`Complaint_nickname`,`Complaint_title`,`Complaint_content`,`Complaint_url`,`Red_id`,`Nickname`,`Complaint_status`) VALUES(%s,%s,%s, %s, %s,%s, %s);'''
            self.database.operation(insert_sql,(data["nickname"],data["title"],data["content"],complaint_url, result["Red_id"],result["Nickname"],'待审核'))
            self.log.info("小红书投诉链接数据插入成功")

        except Exception as e:
            self.log.error(f"小红书帖子举报失败:{e}")
            insert_sql = '''INSERT INTO `complaint_status`(`Complaint_nickname`,`Complaint_title`,`Complaint_content`,`Complaint_url`,`Red_id`,`Nickname`,`Complaint_status`) VALUES(%s,%s,%s, %s, %s,%s, %s);'''
            self.database.operation(insert_sql,(data["nickname"],data["title"],data["content"],complaint_url, result["Red_id"],result["Nickname"],'投诉失败'))
            
           


    # 小红书关注，参数：用户主页/笔记链接
    async def follows(self, account_id, url,post_data:dict=None):
        '''
        参数：
            -account_id:账号id
            -url：用户主页链接/帖子链接
        返回：None
        '''
        try:
            create_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if 'https://www.xiaohongshu.com/' not in self.driver.driver.current_url:
                await self.login_by_cookies(account_id=account_id)
            if self.driver.driver.current_url != url:
                self.log.info(f'进入网页：{url}')
                self.driver.get(url)
                await asyncio.sleep(random.uniform(10,15))
            self.log.info('点击关注按钮')
            action_time = datetime.now()
            try:
                note_element = self.driver.find_xpath(XPATH='//div[@class="interaction-container"]')
                self.log.info(f'链接{url}是帖子链接')
                # data = await self.get_one_content()
                try:
                    self.driver.find_xpath(XPATH='//video[@mediatype="video"]')
                    note_type = '视频'
                except:
                    note_type = '图文'
                nickname = note_element.find_element(By.XPATH,'.//span[@class="username"]').text
                if note_element.find_element(By.TAG_NAME,'button').get_attribute('class') == 'reds-button-new follow-button large primary follow-button':
                    self.log.info(f'暂未关注该作者，点击关注')
                    note_element.find_element(By.XPATH,'.//div[@class="note-detail-follow-btn"]').click()
                    time.sleep(2)
                else:
                    self.log.info(f'已经关注过该作者，无需重复关注')
                    return create_response(create_time=create_time,code=HTTPStatus.OK,message='success',response=f'账号{account_id}已关注过该作者，无需重复关注')
            except:
                self.log.info(f'链接{url}不是帖子链接而是作者主页链接')
                try:
                    note_type = None
                    nickname = self.driver.find_xpath(XPATH='//div[@class="user-name"]').text
                    button_element = self.driver.find_xpath(XPATH='//div[@class="info-right-area"]').find_element(By.TAG_NAME,'button')
                    if button_element.get_attribute("class")=='reds-button-new follow-button large primary follow-button':
                        self.log.info(f'暂未关注该作者，点击关注')
                        button_element.click()
                        time.sleep(2)
                    else:
                        self.log.info(f'已经关注过该作者，无需重复关注')
                        return create_response(create_time=create_time,code=HTTPStatus.OK,message='success',response=f'账号{account_id}已关注过该作者，无需重复关注')
                except Exception as e:
                    self.log.error(f'小红书关注失败')
                    return {"status": "error", "message":  f"小红书账号{account_id}关注失败","response":f"原因是：{e}"}
            self.log.info('小红书关注成功')
            # 添加到互动表，
            now_time = datetime.now()
            insert_sql = '''INSERT INTO `xiaohongshu_interaction`(`Account_id`,`Platform`,`Content`,`Type`,`Action`,`URL`,`Interaction_time`,`Result_list`,`Update_time`) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s);'''
            self.database.operation(insert_sql,(account_id,'小红书',None,note_type,'关注',url,action_time,None,now_time))
            self.log.info('关注 已更新到数据库小红书互动表')
            return create_response(create_time=create_time,code=HTTPStatus.OK,message='success',response=f'账号{account_id}关注成功')
        except Exception as e:
            self.log.error(f"账号{account_id}关注失败:{e}")
            return create_response(create_time=create_time,code=HTTPStatus.BAD_REQUEST,message='error',response=f'账号{account_id}关注失败')

    # 小红书取消关注，参数：用户主页/笔记链接
    async def notfollows(self, account_id, url):
        '''
        参数：
            -account_id:账号id
            -url：用户主页链接/帖子链接
        返回：None
        '''
        try:
            create_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if 'https://www.xiaohongshu.com/' not in self.driver.driver.current_url:
                await self.login_by_cookies(account_id=account_id)
            if self.driver.driver.current_url != url:
                self.log.info(f'进入网页：{url}')
                self.driver.get(url)
                await asyncio.sleep(random.uniform(10,15))
            self.log.info('点击关注按钮,取消关注')
            action_time = datetime.now()
            try:
                # self.driver.search_and_click(XPATH='//*[@id="noteContainer"]/div[4]/div[1]/div/div[2]/button',waiting_time=2.0)
                note_element = self.driver.find_xpath(XPATH='//div[@class="interaction-container"]')
                self.log.info(f'链接{url}是帖子链接')
                # data = await self.get_one_content()
                try:
                    self.driver.find_xpath(XPATH='//video[@mediatype="video"]')
                    note_type = '视频'
                except:
                    note_type = '图文'
                nickname = note_element.find_element(By.XPATH,'.//span[@class="username"]').text
                if note_element.find_element(By.TAG_NAME,'button').get_attribute('class') == 'reds-button-new follow-button large outlined follow-button':
                    self.log.info(f'关注该作者，点击取消关注')
                    note_element.find_element(By.XPATH,'.//div[@class="note-detail-follow-btn"]').click()
                    time.sleep(2)
                else:
                    self.log.info(f'暂未关注过该作者，无需点击取消关注')
                    return create_response(create_time=create_time,code=HTTPStatus.OK,message='success',response=f'账号{account_id}暂未关注该作者，无需点击取消关注')
            except Exception as e:
                self.log.info(f'链接{url}不是帖子链接而是作者主页链接')
                try:
                    note_type = None
                    nickname = self.driver.find_xpath(XPATH='//div[@class="user-name"]').text
                    # self.driver.search_and_click(XPATH='//button[@class="reds-button-new follow-button large primary follow-button"]',waiting_time=2.0)  # 用户主页，则可直接关注                                     
                    button_element = self.driver.find_xpath(XPATH='//div[@class="info-right-area"]').find_element(By.TAG_NAME,'button')
                    if button_element.get_attribute("class")=='reds-button-new follow-button large outlined follow-button':
                        self.log.info(f'关注该作者，点击取消关注')
                        button_element.click()
                        time.sleep(2)
                    else:
                        self.log.info(f'暂未关注过该作者，无需点击取消关注')
                        return create_response(create_time=create_time,code=HTTPStatus.OK,message='success',response=f'账号{account_id}暂未关注该作者，无需点击取消关注')
                except Exception as e:
                    self.log.error(f'小红书取消关注失败')
                    return create_response(create_time=create_time,code=HTTPStatus.BAD_REQUEST,message='error',response=f'账号{account_id}取消关注失败')
            self.log.info('小红书取消关注成功')
            # 添加到互动表
            now_time = datetime.now()
            insert_sql = '''INSERT INTO `xiaohongshu_interaction`(`Account_id`,`Platform`,`Content`,`Type`,`Action`,`URL`,`Interaction_time`,`Result_list`,`Update_time`) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s);'''
            self.database.operation(insert_sql,(account_id,'小红书',None,note_type,'取消关注',url,action_time,None,now_time))
            self.log.info('取消关注 已更新到数据库小红书互动表')
            return create_response(create_time=create_time,code=HTTPStatus.OK,message='success',response=f'账号{account_id}取消关注成功')
        except Exception as e:
            self.log.error(f"账号{account_id}取消关注失败:{e}")
            return create_response(create_time=create_time,code=HTTPStatus.BAD_REQUEST,message='error',response=f'账号{account_id}取消关注失败')

    
    async def get_one_content(self,url=None):
        '''爬取具体内容'''
        data = {"nickname":None,"redid":None,"note_form":None,"note_type":None,"post_time_ip":None,"title":None, "content":None, "collects":None,"comments":None,"likes":None,"images_url":[]}
        # pdb.set_trace()
        try:
            if url:
                # data["note_url"] = url
                self.log.info(f'进入网址：{url}获取笔记具体内容')
                self.driver.open_new_tab(url=url)
                time.sleep(random.uniform(20,40))
                self.driver.swith_to_new_window(-1)
                time.sleep(random.uniform(2,5))
            # else:
                # data["note_url"] = self.driver.driver.current_url
            images_url = []
            data["note_type"] = '原创'
            data["note_url"] = self.driver.driver.current_url 
            html = self.driver.driver.page_source 
            soup = BeautifulSoup(html, "lxml")  # html.parser
            data["nickname"] = soup.find_all('span',class_='username')[-1].get_text() if soup.find_all('span',class_='username') else ''
            data["post_time_ip"] = soup.find('span',class_='date').get_text() if soup.find('span', class_='date') else ''
            data["post_time_ip"] = self.covert_time_str(data["post_time_ip"]) if data["post_time_ip"] else ''   # 转换成标准格式
            data["title"] = soup.find('div', id="detail-title").get_text() if soup.find('div', id="detail-title") else ''
            data["content"] = soup.find('div', id="detail-desc").get_text().replace('\n','').strip() if soup.find('div', id="detail-desc") else ''
            likes = soup.find('span', class_="like-wrapper like-active")
            data["likes"] = likes.find('span', class_="count").get_text() if likes and likes.find('span', class_="count") else ''
            comments = soup.find('span', class_="chat-wrapper")
            data["comments"] = comments.find('span', class_="count").get_text() if comments and comments.find('span', class_="count") else ''
            collects = soup.find('span', id="note-page-collect-board-guide")
            data["collects"] = collects.find('span', class_="count").get_text() if collects and collects.find('span', class_="count") else ''
            data["likes"]  = '0' if data["likes"] == '点赞' else data["likes"] 
            data["comments"]  = '0' if data["comments"] == '评论' else data["comments"]
            data["collects"]  = '0' if data["collects"] == '收藏' else data["collects"]
            video_element = soup.find('video',mediatype="video")
            if not video_element:
                data["note_form"] = '图文'
                images_element = soup.find('div',class_="swiper-wrapper").find_all('img',class_='note-slider-img')
                for image_element in images_element:
                    if image_element.get("src") not in images_url:
                        images_url.append(image_element.get("src"))
                data["images_url"] = images_url
            else:
                data["note_form"] = '视频'
            # 点击头像，进入主页获取账号的redid
            href = self.driver.find_xpath(XPATH='//div[@class="author-container"]').find_element(By.TAG_NAME,'a').get_attribute("href")
            await asyncio.sleep(random.uniform(3,5))
            if not url:
                self.driver.open_new_tab(url=href)
                time.sleep(random.uniform(10,30))
                self.driver.swith_to_new_window(id=-1)
                time.sleep(random.uniform(3,10))
                data["redid"] = self.driver.find_xpath(XPATH='//span[@class="user-redId"]').text.replace('小红书号：','')
                await self.close_now_windows()
            if url:
                # 点击作者头像
                self.driver.get(url=href)
                # self.driver.search_and_click(XPATH='//div[@class="author-wrapper"]//a[contains(@href,"/user/profile")]',waiting_time=5.0)
                time.sleep(random.uniform(10,30))
                data["redid"] = self.driver.find_xpath(XPATH='//span[@class="user-redId"]').text.replace('小红书号：','')
                await self.close_now_windows()
            return data
        except Exception as e:
            self.log.error(f'爬取小红书内容失败，原因是：{e}')
            if url:
               await self.close_now_windows()
            return {}  
        

    async def get_one_comment(self,comments_element):
        try:
            author_url = comments_element.find_element(By.XPATH,'.//div[@class="author"]/a').get_attribute("href").split('?')[0]
            author_nickname = comments_element.find_element(By.XPATH,'.//div[@class="author"]/a').text
            comment_content = comments_element.find_element(By.XPATH,'.//div[@class="content"]/span')
            if comment_content.find_elements(By.XPATH,'.//a[@class="note-content-user"]'):
                at_user = comment_content.find_elements(By.XPATH,'.//a[@class="note-content-user"]')
                at_user_urls = [user.get_attribute("href").split('?')[0] for user in at_user]
            else:
                at_user_urls = []
                
            comment_content = comment_content.text
            comment_emoji = comments_element.find_elements(By.XPATH,'.//img[@class="note-content-emoji"]')

            if comment_emoji:
                comment_emoji = [emoji.get_attribute("src") for emoji in comment_emoji]
            comment_picture = comments_element.find_elements(By.XPATH,'.//img[@class="comment-picture"]')
            if comment_picture:
                comment_picture = comment_picture.find_elements(By.XPATH,'.//img')
                comment_picture = [picture.get_attribute("src") for picture in comment_picture]
            comment_label = comments_element.find_elements(By.XPATH,'.//div[@class="labels"]')
            if comment_label:
                comment_label = [comment_label[0].text]
            comment_info = comments_element.find_elements(By.XPATH,'.//div[@class="info"]')
            if comment_info:
                comment_time = comment_info[0].find_element(By.XPATH,'.//span').text
                comment_ip = comment_info[0].find_element(By.XPATH,'.//span[@class="location"]').text
                comment_interaction = comment_info[0].find_element(By.XPATH,'.//div[@class="interactions"]')
                likes_count = comment_interaction.find_element(By.XPATH,'.//div[@class="like"]').text.replace('赞','')
                replies_count = comment_interaction.find_element(By.XPATH,'.//div[@class="reply icon-container"]').text.replace('回复','')

            else:
                comment_time = None
                comment_ip = None
                comment_interaction = None
                likes_count = None
                replies_count = None
            data={
                "author_url": author_url,
                "nickname": author_nickname,
                "content": comment_content,
                'at_user_urls': at_user_urls,
                "emoji": comment_emoji,
                "picture": comment_picture,
                "label": comment_label,
                "time": comment_time,
                "ip": comment_ip,
                "likes": likes_count,
                "replies": replies_count
            }
            self.log.info(f'获取到评论内容：{data}')
            
            return data
        except Exception as e:
            self.log.error(f'获取一条评论内容失败，原因是：{e}')
            return None


    async def scrap_comments(self,url=None,scrap_time=5,num=100):
        '''
        滑动页面，获取曝光内容,默认是滑动首页
        '''
        try:
            results = []
            # self.driver.get(url)
            # time.sleep(20)
            current_url = self.driver.driver.current_url
            if current_url != url:
                self.log.info(f'进入网址：{url}获取评论的具体内容')
                self.driver.open_new_tab(url=url)
                time.sleep(3)
                self.driver.swith_to_new_window(-1)
                time.sleep(5)
            
            result = {}
            self.log.info(f'开始爬取小红书帖子{url}的评论')
        
            first_comment = self.driver.find_xpath(XPATH='//div[@class="parent-comment"]') 
            current_time = datetime.now()
            # pdb.set_trace()
            scrap_num = 0
            while scrap_num < int(num):
                try:
                    self.driver.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", first_comment)
                    origin_comments_element =  first_comment.find_elements(By.XPATH,'.//div[@class="comment-inner-container"]')
                    if not origin_comments_element:
                        self.log.info('没有找到评论内容，可能是网页结构变化')
                        raise ValueError('没有获取到评论内容')
                    origin_comments_element = origin_comments_element[0]
                    # 获取一级评论内容
                    comment_data = await self.get_one_comment(origin_comments_element)
                    if not comment_data:
                        self.log.info('没有获取到评论内容')
                        raise ValueError('没有获取到评论内容')
                    result['comment'] = comment_data
                    now_time = datetime.now()
                    insert_sql = '''INSERT INTO `comment_records`(`Platform`,`Post_url`,`Commenter_nickname`,`Commenter_url`,`Content`,`At_users`,`Emojis`,`Pictures`,`Label`,`Comment_time`,`Comment_ip`,`Comment_likes`,`Comment_replies`,`Update_time`) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s);'''
                    self.database.operation(insert_sql,('小红书',url,comment_data['nickname'],comment_data['author_url'],comment_data['content'],str(comment_data['at_user_urls']),str(comment_data['emoji']),str(comment_data['picture']),str(comment_data['label']),comment_data['time'],comment_data['ip'],comment_data['likes'],comment_data['replies'],now_time))
                    self.log.info('已更新小红书评论表')

                    # 获取评论的回复内容
                    if not comment_data['replies']:
                        self.log.info("这条评论没有回复，跳过")
                        raise ValueError("这条评论没有回复，跳过")

                    replies_element = first_comment.find_elements(By.XPATH,'.//div[@class="reply-container"]')
                    self.driver.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", replies_element[0])
                    show_element = replies_element[0].find_elements(By.XPATH,'.//div[@class="show-more"]')
                    while show_element:
                        try:
                            self.driver.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", show_element[0])
                            self.log.info('点击展开更多评论')
                            time.sleep(1)
                            show_element[0].click()
                            time.sleep(2)
                            show_element = replies_element[0].find_elements(By.XPATH,'.//div[@class="show-more"]')
                            if current_time + timedelta(minutes=scrap_time) < datetime.now():
                                break
                        except Exception as e:
                            self.log.error(f'展开评论失败，原因是：{e}')
                            break
                    replies_element = first_comment.find_elements(By.XPATH,'.//div[@class="reply-container"]')
                    replies_elements = replies_element[0].find_elements(By.XPATH,'.//div[@class="comment-item comment-item-sub"]')
                    replies_data = []
                    for reply_element in replies_elements:
                        reply_data = await self.get_one_comment(reply_element)
                        time.sleep(random.randint(3,5))
                        if reply_data:
                            now_time = datetime.now()
                            insert_sql = '''INSERT INTO `reply_records`(`Platform`,`Post_url`,`Comment_content`,`Commenter_nickname`,`Commenter_url`,`Content`,`At_users`,`Emojis`,`Pictures`,`Label`,`Comment_time`,`Comment_ip`,`Comment_likes`,`Comment_replies`,`Update_time`) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s);'''
                            self.database.operation(insert_sql,('小红书',url,comment_data['content'],reply_data['nickname'],reply_data['author_url'],reply_data['content'],str(reply_data['at_user_urls']),str(reply_data['emoji']),str(reply_data['picture']),str(reply_data['label']),reply_data['time'],reply_data['ip'],reply_data['likes'],reply_data['replies'],now_time))
                            self.log.info('已更新小红书回复表')
                            replies_data.append(reply_data)
                    result['replies'] = replies_data
                    results.append(result)
                    self.log.info(f'获取到评论内容：{comment_data}')
                    self.log.info(f'获取到{len(replies_data)}条回复内容')
                    time.sleep(random.randint(1,5))
                    first_comment = first_comment.find_element(By.XPATH,'following::div[@class="parent-comment"]')
                    
                    scrap_num += 1
                    
                except Exception as e:
                    self.log.error(f'获取评论内容失败，原因是：{e}')
                    first_comment = first_comment.find_element(By.XPATH,'following::div[@class="parent-comment"]')
                    time.sleep(random.randint(1,3))
                    scrap_num += 1
            if current_url != url:
                self.driver.close()
                self.driver.swith_to_new_window(-1)
                time.sleep(1)
        except Exception as e:
            
            self.log.error(f'爬取帖子{url}的评论失败:{e}')
            if current_url != url:
                self.driver.close()
                self.driver.swith_to_new_window(-1)
                time.sleep(1)
        return results
        

    




    async def scrap_content(self,account_id,num=10,url=None,keyword=None,is_comments=False,scrap_time=5):
        '''
        滑动页面，获取曝光内容,默认是滑动首页
        '''
        try:
            create_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            await self.login_by_cookies(account_id=account_id)
            self.log.info('进入小红书首页')
            
            if not url:
                self.driver.get(url = 'https://www.xiaohongshu.com/')
            else:
                self.driver.get(url = url)
            if keyword:
                self.log.info(f'搜索关键词：{keyword}')
                element = self.driver.find_xpath(XPATH='//input[@id="search-input"]')
                element.send_keys(keyword)
                time.sleep(random.randint(1,5))
                element.send_keys(Keys.ENTER)
                # pdb.set_trace()
                time.sleep(5)
                url =  self.driver.driver.current_url
                filter_button = self.driver.find_xpath(XPATH='//div[@class="filter"]')
                #筛选最新帖子
                actions = ActionChains(self.driver.driver)
                actions.move_to_element(filter_button).perform()
                time.sleep(random.randint(1,3))
                
                filter_element = self.driver.find_xpaths(XPATH='//div[@class="filter-panel"]')
                if filter_element:
                    self.log.info("点击筛选-最新按钮")
                    filter_element[0].find_element(By.XPATH,'.//span[contains(text(),"最新")]').click()
                    time.sleep(1)
                    #筛选发布时间：一周内
                    # filter_element.find_element(By.XPATH,'.//span[contains(text(),"一周内")]').click()
                    #点击收起，筛选最新帖子后filterbutton会变化
                
                    self.driver.find_xpath(XPATH='//div[@class="filter-panel"]').find_element(By.XPATH,'.//div[contains(text(),"收起")]').click()
                else:
                    filter_element = self.driver.find_xpath(XPATH='/html/body/div[5]/div/li[2]/span')
                    actions.move_to_element(element).perform()

            time.sleep(5)
            self.log.info(f'开始爬取{num}条推荐的内容')
            scrap_num = 0
            stored_urls = set()
            results = []
            comment_reply = []
            while scrap_num < num:
                html = self.driver.driver.page_source 
                soup = BeautifulSoup(html, "lxml")  # html.parser
                notes = soup.find_all("section", class_="note-item")
                if len(notes) == 0 :
                    self.log.warning("未找到新内容，可能是网页结构变化")
                    break
                for note in notes:
                    if scrap_num >= num:  
                        break
                    try:
                        note_element = note.find('a', class_='cover mask ld')
                        if not note_element:
                            continue
                        href = note_element.get("href")
                        full_url = urljoin('https://www.xiaohongshu.com', href) # 完整的链接
                    except AttributeError:
                        self.log.warning("网页结构可能已变化，未找到 note 元素")
                        continue
                    if full_url not in stored_urls:
                        # check_sql = f"SELECT * FROM xiaohongshu_records WHERE URL = '{full_url}'"
                        # check_result = self.database.get_dict_data_sql(check_sql)
                        # if check_result:
                        #     self.log.info(f'文章{full_url}已经存在于数据库中，不再继续添加')
                        #     continue
                        stored_urls.add(full_url)
                        scrap_num += 1
                        
                self.driver.scroll(size=500) # 滑动页面
                
            for full_url in stored_urls:
                # 获取笔记具体的内容
                data = await self.get_one_content(url = full_url)
                if not data:
                    continue
                data["URL"] = full_url
                results.append(data)
                # 则添加到曝光表
                
                if is_comments:
                    # 爬取评论
                    now_time = datetime.now()
                    insert_sql = '''INSERT INTO `post_records`(`Account_id`,`Platform`,`URL`,`Source_nickname`,`Source_redid`,`Title`,`Content`,`Likes_Num`,`Collects_Num`,`Comments_Num`,`Published_Time_IP`,`Type`,`Form`,`Images_URL`,`Update_time`) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s);'''
                    self.database.operation(insert_sql,(account_id,'小红书',full_url,data["nickname"],data["redid"],data["title"],data["content"],data["likes"],data["collects"],data["comments"],data["post_time_ip"],data["note_type"],data["note_form"],str(data["images_url"]),now_time))
                    self.log.info('已更新小红书贴文曝光表')
                    self.log.info(f'开始爬取帖子{full_url}的评论')
                    if data['comments']:
                        await self.scrap_comments(url=full_url,scrap_time=scrap_time,num=data['comments'])
                else:
                    now_time = datetime.now()
                    insert_sql = '''INSERT INTO `xiaohongshu_records`(`Account_id`,`Platform`,`URL`,`Source_nickname`,`Source_redid`,`Title`,`Content`,`Likes_Num`,`Collects_Num`,`Comments_Num`,`Published_Time_IP`,`Type`,`Form`,`Images_URL`,`Update_time`) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s);'''
                    self.database.operation(insert_sql,(account_id,'小红书',full_url,data["nickname"],data["redid"],data["title"],data["content"],data["likes"],data["collects"],data["comments"],data["post_time_ip"],data["note_type"],data["note_form"],str(data["images_url"]),now_time))
                    self.log.info('已更新小红书内容曝光表')

            self.log.info(f'账号{account_id}获取到的曝光内容是：{results}')
            # 添加到互动表，
            insert_sql = '''INSERT INTO `xiaohongshu_interaction`(`Account_id`,`Platform`,`Content`,`Type`,`Action`,`URL`,`Interaction_time`,`Result_list`,`Update_time`) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s);'''
            self.database.operation(insert_sql,(account_id,'小红书',str(results),'None','滑动','https://www.xiaohongshu.com/',now_time,None,now_time))
            self.log.info('滑动 已更新到数据库小红书互动表')  
            
            
            return create_response(create_time=create_time,code=HTTPStatus.OK,message='success',response=results)
        except Exception as e:
            self.log.info(f'账号{account_id}滑动页面，获取曝光内容失败，原因是：{e}')     
            return create_response(create_time=create_time,code=HTTPStatus.BAD_REQUEST,message='error',response=f'账号{account_id}滑动页面，获取曝光内容失败')
        
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
            sql = f"SELECT * FROM xiaohongshu_records WHERE Account_id = {account_id}"
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
        
    async def get_account_interaction(self,account_id):
        '''从数据库中获取账号的历史交互'''
        try:
            # pdb.set_trace()
            create_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            sql = f"SELECT * FROM xiaohongshu_interaction WHERE Account_id = {account_id}"
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
      
    



    async def act_recommend_content(self,account_id,actions:list=['点赞','评论','收藏'],act_num:int=10,person_id=None,model='Qwen2.5-14b-Instruct'):
        '''
        在 xhs 首页推荐页面，浏览内容，并根据人设判断是否感兴趣，若敢兴趣则执行actions，若不感兴趣则不执行动作,共执行 act_num  次
        '''

        try:
            # pdb.set_trace()
            if 'https://www.xiaohongshu.com/' not in self.driver.driver.current_url:
                await self.login_by_cookies(account_id=account_id)
            
            self.log.info(f'进入小红书首页推荐页面')
            self.driver.get(url  =  'https://www.xiaohongshu.com/explore?channel_id=homefeed_recommend')
            await asyncio.sleep(random.uniform(10,15))

            results = []
            select_num = 0

            # 获取账号人设
            characters = get_character(account_id=account_id,person_id=person_id,database=self.database)
            self.log.info(f'账号{account_id}的人设是：{characters}')

            # 开始浏览页面，获取内容
            article_element = self.driver.find_xpath(XPATH='//section[@class="note-item"]')
            
            while select_num < act_num:
                await asyncio.sleep(random.uniform(1,2))
                self.driver.driver.execute_script("""arguments[0].scrollIntoView({ behavior: 'smooth', block: 'center' });""",article_element)
                await asyncio.sleep(random.uniform(1,5))
                article_url  = article_element.find_element(By.XPATH,'.//a[@class="cover mask ld"]').get_attribute('href')
                self.log.info(f'进入{article_url}')
                self.driver.open_new_tab(url=article_url)
                await asyncio.sleep(random.uniform(10,15))
                self.driver.swith_to_new_window(id=-1)
                await asyncio.sleep(random.uniform(1,3))
                # 获取页面内容
                data = await self.get_one_content()
                if not data:
                    self.log.info(f'未获得有效内容')
                    await self.close_now_windows()
                    try:
                        article_element = article_element.find_element(By.XPATH, "following-sibling::section[@class='note-item']")
                    except:
                        self.log.info(f'未找到下一个笔记')
                        return {"status": "success", "message": f"小红书账号{account_id}浏览热门推荐内容成功","response":f"小红书账号{account_id}互动的热门推荐帖子是：{results}"}
                    continue
                data['note_url']  = article_url
                # 添加到曝光表中
                add_time = datetime.now()
                insert_sql = '''INSERT INTO `xiaohongshu_records`(`Account_id`,`Platform`,`URL`,`Source_nickname`,`Source_redid`,`Title`,`Content`,`Likes_Num`,`Collects_Num`,`Comments_Num`,`Published_Time_IP`,`Type`,`Form`,`Images_URL`,`Update_time`) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s);'''
                self.database.operation(insert_sql,(account_id,'小红书',data['note_url'],data["nickname"],data["redid"],data["title"],data["content"],data["likes"],data["collects"],data["comments"],data["post_time_ip"],data["note_type"],data["note_form"],str(data["images_url"]),add_time))
                self.log.info('已更新小红书内容曝光表')
                try_num = 0 
                while True:
                    try:
                        post_content = (data.get("title") or "") + (data.get("content") or "")
                        # 判断内容是否感兴趣
                        response = await interest_detection(account_id=account_id,characters=characters,content=post_content,database=self.database)
                        self.log.info(f"判断是否感兴趣内容生成结果为:{response}")
                        if 'no' in response.lower():
                            self.log.info(f'账号{account_id}对该内容不感兴趣，继续查找下一个')
                            break
                        if 'yes' in response.lower():
                            action = random.choice(actions)
                            self.log.info(f'账号{account_id}对内容感兴趣，执行 {action} 动作')
                            if action == '点赞':
                                await self.likes(account_id=account_id,url=article_url,post_data=data)
                            elif action == '评论':
                                content,_ = await generation_comment(text=post_content,language='中文简体',output_len=100,character=characters,model=model) # 生成评论内容
                                await self.comments(account_id=account_id,url=article_url,content=content,post_data=data)
                            elif action == '收藏':
                                await self.collects(account_id=account_id,url=article_url,post_data=data)
                            await asyncio.sleep(random.uniform(2,5))
                            
                            select_num += 1
                            results.append(data)
                            break
                        else:
                            self.log.error(f"生成格式错误，解析失败: {e}")
                            try_num += 1
                            if try_num > 5:
                                break

                    except Exception as e:
                        self.log.error(f"生成格式错误，解析失败: {e}")
                        try_num += 1
                        if try_num > 5:
                            break
                await self.close_now_windows()
                # 检测账号是否下线
                try:
                    self.driver.find_xpath(XPATH='//div[@class="login-container"]')
                    self.log.info(f'账号{account_id}下线，请重新登录')
                    return {"status": "success", "message": f"小红书账号{account_id}下线，请重新登录","response":f"小红书账号{account_id}下线，请重新登录。互动的热门推荐帖子是：{results}"}
                except:
                    pass
                # 找到下一个内容
                try:
                    article_element = article_element.find_element(By.XPATH, "following-sibling::section[@class='note-item']")
                except:
                    self.log.info(f'未找到下一个笔记')
                    return {"status": "success", "message": f"小红书账号{account_id}浏览热门推荐内容成功","response":f"小红书账号{account_id}互动的热门推荐帖子是：{results}"}
            return {"status": "success", "message": f"小红书账号{account_id}浏览热门推荐内容成功","response":f"小红书账号{account_id}互动的热门推荐帖子是：{results}"}
        except Exception as e:
            self.log.error(f'账号{account_id}获取热门推荐的内容失败，原因是：{e}')
            return {"status": "error", "message": f"微博账号{account_id}浏览热门推荐内容失败","response":f"原因是：{e}"}
        

    async def close_now_windows(self):
        '''关闭当前窗口 并将driver切换到最新窗口'''
        self.driver.close()
        await asyncio.sleep(random.uniform(2,4))
        self.driver.swith_to_new_window(id=-1)
        await asyncio.sleep(random.uniform(2,5))

    def scroll(self,duration):
        '''在一个页面滑动时长'''
        start_time = time.time()
        while time.time() - start_time < duration:
            self.driver.scroll(size=random.uniform(100,500))
            time.sleep(random.uniform(0.5, 5))


    async def get_one_keyword_content(self,account_id,keyword:str=None,article=None):
        '''获取一个贴文的内容 不关闭窗口，然后返回。'''
        create_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            
            if 'https://www.xiaohongshu.com/' not in self.driver.driver.current_url:
                await self.login_by_cookies(account_id=account_id)

            # pdb.set_trace()

            # article 元素是否存在
            if not article:
                try:
                    keyword  = keyword +'论文'
                    self.driver.get(url = f'https://www.xiaohongshu.com/search_result?keyword={keyword}&source=web_explore_feed')
                    self.log.info(f'搜索关键字 “{keyword}” 获取帖子 ')
                    await asyncio.sleep(random.uniform(30,60))
                    # note_type = random.choice(['最新','最热','最多评论','最多点赞'])
                    note_type = '最新'  # 点击最新/最热
                    filter_div = WebDriverWait(self.driver.driver, 10).until(EC.presence_of_element_located((By.XPATH, '//div[@class="filter"]')))
                    ActionChains(self.driver.driver).move_to_element(filter_div).perform()
                    time.sleep(random.uniform(3,10))
                    self.driver.search_and_click(XPATH=f'//div[@class="tags" and .//span[text()="{note_type}"]]',waiting_time=random.uniform(4,10)) 
                    # 找到第一个元素
                    article = self.driver.find_xpath(XPATH='//section[@class="note-item" and .//a[@class="cover mask ld"]]')
                except:
                    self.log.info(f'未找到任何的相关内容，返回')
                    return {},None
            else:
                article = article.find_element(By.XPATH,'following-sibling::section[@class="note-item" and .//a[@class="cover mask ld"]]')

            self.driver.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", article)
            time.sleep(random.uniform(2,4))
            ActionChains(self.driver.driver).move_to_element(article).perform()
            time.sleep(random.uniform(10,20))

            article_url = article.find_element(By.XPATH,'.//a[@class="cover mask ld" and contains(@href,"/search_result/")]').get_attribute("href")
            
            self.log.info(f'打开帖子：{article_url} 获取具体的贴文内容')
            # data = await self.get_one_content()
            self.driver.open_new_tab(url=article_url)
            time.sleep(random.uniform(20,50))
            self.driver.swith_to_new_window(id=-1)
            time.sleep(random.uniform(2,5))
            data = await self.get_one_content()
            data["keyword"] = keyword
            data['note_url'] = article_url
            self.log.info(f'搜索热搜词{keyword}获取的曝光内容是:{data}')
            # 转换post_time_ip,将时间转换成标准格式(str)类型
            # "编辑于 46分钟前 辽宁" “2小时前 天津”  ，“昨天 20:47 广东”，“编辑于 1天前 北京”  “5天前 山西”
            data["post_time_ip"] = self.covert_time_str(data["post_time_ip"])
            # 添加到曝光表中
            insert_sql = '''INSERT INTO `xiaohongshu_records`(`Account_id`,`Platform`,`URL`,`Source_nickname`,`Source_redid`,`Title`,`Content`,`Likes_Num`,`Collects_Num`,`Comments_Num`,`Published_Time_IP`,`Type`,`Form`,`Images_URL`,`Update_time`) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s);'''
            self.database.operation(insert_sql,(account_id,'小红书',data['note_url'],data["nickname"],data["redid"],data["title"],data["content"],data["likes"],data["collects"],data["comments"],data["post_time_ip"],data["note_type"],data["note_form"],str(data["images_url"]),datetime.now()))
            self.log.info('已更新小红书内容曝光表')

            return  data,article

        except Exception as e:
            self.log.error(f'获取关键词内容失败，失败原因是：{e}')
            return {},None
        

    def covert_time_str(self,time_str:str,floor_to_midnight:bool=True):
        '''
        将 "编辑于 46分钟前 辽宁" “2小时前 天津”  ，“昨天 20:47 广东”，“编辑于 1天前 北京”  “5天前 山西” 转换成标准格式(str)类型（2025-10-21 00:00:00）
        '''
        
        # _CN_TZ = ZoneInfo("Asia/Shanghai")
        now = datetime.now()

        # 预处理：全角冒号 -> 半角；去“编辑于”
        text = time_str.strip().replace("：", ":")
        text = re.sub(r"^\s*编辑于\s*", "", text)

        m_abs_full = re.search(
            r"(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T](\d{1,2}):(\d{1,2})(?::(\d{1,2}))?)?",
            text
        )
    
        if m_abs_full:
            y, mo, d = (int(m_abs_full.group(i)) for i in range(1, 4))
            hh = int(m_abs_full.group(4) or 0)
            mm = int(m_abs_full.group(5) or 0)
            ss = int(m_abs_full.group(6) or 0)
            dt = datetime(y, mo, d, hh, mm, ss)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        
        m_abs_md = re.search(
            r"(?<!\d)(\d{1,2})-(\d{1,2})(?:[ T](\d{1,2}):(\d{1,2})(?::(\d{1,2}))?)?",
            text
        )
        if m_abs_md:
            mo, d = int(m_abs_md.group(1)), int(m_abs_md.group(2))
            hh = int(m_abs_md.group(3) or 0)
            mm = int(m_abs_md.group(4) or 0)
            ss = int(m_abs_md.group(5) or 0)
            year = now.year
            dt = datetime(year, mo, d, hh, mm, ss)
            # 若只有日期且需要对齐到 00:00:00
            if floor_to_midnight and m_abs_md.group(3) is None:
                dt = dt.replace(hour=0, minute=0, second=0, microsecond=0)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
    

        # 匹配
        m_min  = re.search(r"(\d+)\s*分(?:钟)?\s*前", text)
        m_hour = re.search(r"(\d+)\s*小?时\s*前", text)
        m_day  = re.search(r"(\d+)\s*天\s*前", text)
        m_yday = re.search(r"昨[天日](?:\s+(\d{1,2})(?::(\d{1,2}))?)?", text)

        if m_min:
            dt = now - timedelta(minutes=int(m_min.group(1)))
        elif m_hour:
            dt = now - timedelta(hours=int(m_hour.group(1)))
        elif m_day:
            base = now - timedelta(days=int(m_day.group(1)))
            dt = base.replace(hour=0, minute=0, second=0, microsecond=0) if floor_to_midnight \
                else base.replace(second=0, microsecond=0)
        elif m_yday:
            base = now - timedelta(days=1)
            if m_yday.group(1):  # 昨天 HH[:MM]
                hh = int(m_yday.group(1))
                mm = int(m_yday.group(2) or 0)
                dt = base.replace(hour=hh, minute=mm, second=0, microsecond=0)
            else:                 # 只有“昨天”
                dt = base.replace(hour=0, minute=0, second=0, microsecond=0) if floor_to_midnight \
                    else base.replace(second=0, microsecond=0)
        else:
            raise ValueError(f"无法解析时间字符串：{time_str!r}")

        return dt.strftime("%Y-%m-%d %H:%M:%S")
        


    async def get_notifications(self,account_id,time_limit):
        '''获取账号account_id的通知，如果是评论/回复的通知，则要回复他人'''
        create_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            '''
            获取的内容要加入到 xiaohongshu_notification数据表中
            '''
            # 检查如果当前账号没有登录成功，则登录
            try:
                href = self.database.get_dict_data_sql(sql=f'SELECT  * FROM accounts_info WHERE Account_id = {account_id}')[0]['URL']
                if href == self.driver.find_xpath(XPATH='//div[@class="active router-link-exact-active link-wrapper" and contains(@href,"/user/profile")]').get_attribute('href'):
                    self.log.info(f'账号{account_id}登录正常')
                else:
                    self.log.info(f'登录账号{account_id}')
                    await self.login_by_cookies(account_id=account_id)
            except:
                self.log.info(f'登录账号{account_id}')
                await self.login_by_cookies(account_id=account_id)
            pdb.set_trace()
            # 刷新页面
            self.log.info(f'刷新页面')
            self.driver.driver.refresh()
            time.sleep(random.uniform(random.uniform(5,10),random.uniform(20,30)))
            action_time = datetime.now()
            notify_informations = []
            # 检查是否存在未读的通知
            # try:
            #     count = self.driver.find_xpath(XPATH='//a[@href="/notification" and .//div[@class="count"]]').text.replace('通知','').strip()
            #     self.log.info(f'账号{account_id} 存在 {count} 条未读通知，进入通知页面')
            # except:
            #     self.log.info(f'不存在未读通知，直接返回')
            #     return create_response(create_time=create_time,code=HTTPStatus.OK,message='success',response=[])   # 不存在新通知，则返回空list
            
            # time_limit转换成datetime类型的时间
            if isinstance(time_limit,str):
                notification_start_time = self.parse_time_string(time_string=time_limit)
            if isinstance(time_limit,datetime):
                notification_start_time = time_limit
            self.log.info(f'获取的通知开始时间是：{notification_start_time}')
            
            self.driver.get(url = 'https://www.xiaohongshu.com/notification') # 进入通知页面
            await asyncio.sleep(random.uniform(10,30))
  
            # 点击其他的
            click_count = 0 
            while True:
                if click_count !=  0:
                    try:
                        self.driver.search_and_click(XPATH='//div[@class="reds-tab-item tab-item" and .//div[@class="count"]]',waiting_time=random.uniform(2,5))
                    except:
                        self.log.info(f'所有的通知消息都已经获取完成')
                        break
                note_type = self.driver.find_xpath(XPATH='//div[@class="reds-tab-item active tab-item"]//span').text
                self.log.info(f'当前处理的消息类型为：{note_type}')
                article = self.driver.find_xpath(XPATH='//div[@class="container"]')
                while True:
                    try:
                        self.driver.search_and_click(XPATH='//button[@class="load-more-button"]',waiting_time=random.uniform(2,5))
                        self.log.info(f'点击 查看更多历史消息 按钮')
                    except:
                        self.log.info(f'暂时未出现 查看更多历史消息 按钮')

                    self.driver.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", article)
                    time.sleep(random.uniform(random.uniform(2,5),random.uniform(5,10)))
                    notify_info =  await self.get_notifications_details(account_id=account_id,article=article)
                    time.sleep(random.uniform(random.uniform(2,5),random.uniform(5,10)))
                    if not notify_info:
                        self.log.info(f'原评论已经删除，不计入数据统计')
                        try:
                            article = article.find_element(By.XPATH,'following-sibling::div[@class="container"]')
                            time.sleep(random.uniform(random.uniform(2,5),random.uniform(5,10)))
                        except:
                            self.log.info(f'已经查找完所有 {note_type} 的通知内容')
                            break
                        continue
                    # 比较时间
                    if datetime.strptime(notify_info['notify_time'], "%Y-%m-%d %H:%M:%S") < notification_start_time:
                        self.log.info(f'已经查找完{notification_start_time}之后的所有通知')
                        break

                    # 检查数据库中是否已经存在这条数据，如果存在，则表示已经获取完所有的通知
                    select_sql = f'''SELECT * FROM xiaohongshu_notification WHERE Account_id = {account_id} AND Notify_Type  = "{notify_info['notify_type']}" AND Actor_URL =  "{notify_info['actors_url'][0]}" AND Original_Note_URL = "{notify_info['original_url']}";'''
                    select_result  = self.database.get_dict_data_sql(sql=select_sql)
                    if select_result:
                        self.log.info(f'该通知在数据库中已经存在，说明已经获取完所有的{note_type}通知')
                        break
                    # 插入数据库
                    insert_sql = '''INSERT INTO `xiaohongshu_notification`(`Account_id`,`Platform`,`Notify_Time`,`Notify_Type`,`Comment_Content`,`Comment_URL`,`Actor_Nickname`,`Actor_URL`,`Original_Note_URL`,`Original_Content`,`Update_Time`) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s);'''
                    self.database.operation(insert_sql,(account_id,'xiaohongshu',notify_info['notify_time'],notify_info['notify_type'],notify_info['content'],notify_info['note_url'],notify_info['actor_nickname'],notify_info['actors_url'][0],notify_info['original_url'],notify_info['original_content'],datetime.now()))
                    self.log.info(f'{notify_info} 已更新到数据库小红书通知表')
                    # 如果类型是 回复/评论,则要回复他人
                    if notify_info['notify_type'] == 'commented' or notify_info['notify_type'] == 'replied':
                        await self.reply_notify_content(account_id=account_id,article=article,notify_information=notify_info)
                        self.log.info(f'回复评论完成')
                    # 查找下一个通知
                    try:
                        article = article.find_element(By.XPATH,'following-sibling::div[@class="container"]')
                        time.sleep(random.uniform(random.uniform(2,5),random.uniform(5,10)))
                    except:
                        self.log.info(f'已经查找完所有 {note_type} 的通知内容')
                        break
                click_count += 1
            return action_time   # 作为新的时间节点
        except Exception as e:
            self.log.error(f'获取账号{account_id}的通知失败，原因是：{e}')


    async def get_notifications_details(self,account_id,article):
        '''获取通知的具体内容，然后返回一个dict'''
        try:
            # article = self.driver.find_xpath(XPATH='//div[@class="container"]')
            
            actor_url = article.find_element(By.XPATH,'.//div[@class="user-info"]').find_element(By.TAG_NAME,'a').get_attribute("href") # 用户主页链接
            actor_nickname = article.find_element(By.XPATH,'.//div[@class="user-info"]').find_element(By.TAG_NAME,'a').text.strip().replace('\n','')
            notify_time =  article.find_element(By.XPATH,'.//span[@class="interaction-time"]').text  
            notify_time = datetime.now() if notify_time == '刚刚' else self.covert_time_str(notify_time)   # 要转换成时间戳
            

            # 通知类型
            reply_text = article.find_element(By.XPATH,'.//div[@class="interaction-hint"]/span[1]').text
            if '赞了' in  reply_text:
                notify_type = 'liked'
            elif '回复了'  in reply_text:  # 回复了评论
                notify_type = 'replied'
            elif '评论了'  in reply_text: # 评论了笔记
                notify_type = 'commented'
            elif  '收藏了' in reply_text:
                notify_type = 'collected'
            elif  '开始关注你了' in reply_text or '关注了你' in reply_text:
                notify_type = 'followed'

            try:
                original_content = article.find_element(By.XPATH,'.//div[@class="quote-info"]').text.split('\n')  # 我发出去的评论内容  【】
                original_content = str(original_content)  # 变成字符串
            except:
                original_content = ''
            try:
                content = article.find_element(By.XPATH,'.//div[@class="interaction-content"]').text.strip().replace('\n','') # 别人评论/回复的内容
            except:
                content = ''

            if  content == '原评论已删除' or original_content == '原评论已删除':
                self.log.info(f'原评论已删除')   
                return []


            # 点击 ，获取笔记的具体内容
            if  reply_text == '赞了你的笔记' or reply_text == '收藏了你的笔记' or reply_text == '评论了你的笔记':
                # 点击article，获取贴文链接
                old_url = self.driver.driver.current_url
                # wait = WebDriverWait(self.driver.driver, 12)
                # node = wait.until(EC.presence_of_element_located((By.XPATH, f"//*[normalize-space(text())='{text}']")))
                node = article.find_element(By.XPATH,'.//div[@class="extra"]//img')
                clickable = self.driver.driver.execute_script("""  const n = arguments[0];  return n.closest('a,button,[role=\"button\"],[onclick],.interaction-content,.quote-info') || n;""", node)
                self.driver.driver.execute_script("arguments[0].scrollIntoView({block:'center', inline:'center'});", clickable)
                try:
                    ActionChains(self.driver.driver).move_to_element(clickable).pause(0.2).click().perform()
                    await asyncio.sleep(random.uniform(5,10))
                except Exception:
                    pass
                # 获取贴文链接
                if old_url != self.driver.driver.current_url:
                    # 帖子打开成功，关闭
                    self.log.info(f'帖子打开成功，获取贴文内容')
                    note_info = await self.get_one_content()
                    self.log.info(f'获得的贴文内容是：{note_info}')
                    self.log.info(f'点击 关闭 按钮')
                    self.driver.search_and_click(XPATH='//div[@class="close close-mask-dark"]',waiting_time=random.uniform(5,10))
                    notify_info = {
                        "actors_url":[actor_url],
                        "actor_nickname":actor_nickname,
                        "notify_type":notify_type,
                        "notify_time":notify_time,
                        "content":content,
                        "note_url": '',
                        "original_content":note_info['content'],
                        "original_url":note_info['note_url']
                    }
                    return notify_info
                
            # 其他情况：
            notify_info = {
                "actors_url":[actor_url],
                "actor_nickname":actor_nickname,
                "notify_type":notify_type,
                "notify_time":notify_time,
                "content":content,
                "note_url": '',
                "original_content":original_content,
                "original_url":'' 
                
            }
            return notify_info 

        except Exception as e:
            self.log.error(f'获取通知内容失败，{e}')

          

    async def reply_notify_content(self,account_id,article,notify_information:dict):
        '''在通知里 回复别人的评论'''
        try:
            # 获取账号人设
            search_sql = f"SELECT * FROM accounts_info WHERE accounts_info.Account_id = {account_id}"
            character_id = self.database.get_dict_data_sql(search_sql)[0]['Person_id']
            if character_id: # 获取人设
                s = sql_dataset('twitter')
                character_sql = f"SELECT * FROM person WHERE person.Id = {character_id}"
                character = s.get_dict_data_sql(character_sql)[0]["Description"]
            else:
                character = '专心科研的学者，经常在社交平台发布论文相关的内容'

            if notify_information['notify_type'] == 'commented': # 发布的笔记内容
                original_content = notify_information['original_content']
                
            if notify_information['notify_type'] == 'replied': # 回复的评论内容
                original_content = ast.literal_eval(s)[0]

            # 回复评论
            content = await general_generation([{"role":"system","content":reply_comment_prompt(character=character,content=original_content,language='中文')},
                                                {"role":"user","content":notify_information['content']}])
            
            self.log.info(f'模型生成的回复评论内容是：{content}')
            content = ''.join(c for c in content if ord(c) <= 0xFFFF) 
            content = self.cut_content(content,max_length=270)
            self.log.info(f'经过字数检查之后要评论的内容是：{content}')
            # 评论
            action_time = datetime.now()  # 交互开始时间
            self.log.info(f'点击 回复 按钮')
            article.find_element(By.XPATH,'.//div[@class="action-reply"]').click()
            await asyncio.sleep(random.uniform(1,3))
            article.find_element(By.XPATH,'.//textarea[@class="comment-input"]').send_keys(content)
            await asyncio.sleep(random.uniform(2,3))
            article.find_element(By.XPATH,'.//button[@class="submit"]').click()
            await asyncio.sleep(random.uniform(2,5))

            self.log.info(f'账号{account_id}回复用户{notify_information["actors_url"]}评论成功！')
            # 插入数据库
            insert_sql = '''INSERT INTO `xiaohongshu_interaction`(`Account_id`,`Platform`,`Content`,`Type`,`Action`,`URL`,`Interaction_time`,`Result_list`,`Update_time`) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s);'''
            self.database.operation(insert_sql,(account_id,'小红书',original_content ,None,'回复评论',notify_information['original_url'],action_time,content,datetime.now()))
            self.log.info('回复评论 已更新到数据库小红书互动表')

        except Exception  as e:
            self.log.error(f'账号{account_id}回复评论失败，原因是：{e}')




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