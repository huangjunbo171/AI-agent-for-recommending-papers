import os
import sys
pythonpath = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
import time
# from .driver_util import WebDriver
from .base_bot import WebDriver
import os
import re
current_directory = os.path.dirname(os.path.abspath(__file__))
from utils.log import logger
import cv2
import pdb
import random
import requests
from .chaojiying import Chaojiying_Client
from PIL import Image
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException
# usage有 reply_comment comment transmit post
# 衍生的附加属性 post_content comment_content


class WangyiBot():
    def __init__(self, log_path: str = "./logs/email/email_log.log",ip=None,username=None,password=None):
        """
        初始化WeiboBot类的实例。

        参数：
        - log_path：日志文件路径，默认为 father_directory/logs/weibo/weibo_log.log

        返回值：
        无
        """
        super().__init__()
        self.driver = WebDriver(log_path=log_path,ip=ip,username=username,password=password)
        self.log = logger(filename=log_path)

    def load_cookies(self, load_from_file: bool = True, file_path: str = os.path.join(current_directory, "cookies\\twitter_cookies.json"), save_to_file: bool = True, save_path: str = os.path.join(current_directory, "cookies\\twitter_cookies.json")):
        """
        加载cookies。

        参数：
        - load_from_file：是否从文件中读取cookie，默认为True
        - file_path：cookie文件路径，默认为 current_directory/cookies/twitter_cookies.json
        - save_to_file：是否自动保存cookie到文件，默认为True
        - save_path：保存cookie的文件路径，默认为 current_directory/cookies/twitter_cookies.json

        返回值：
        无
        """
        if load_from_file:
            self.driver.read_cookies(cookies_path=file_path)
        else:
            self.driver.get_cookies(
                auto_save=save_to_file, auto_save_path=save_path, url="https://mail.163.com/")



    def login(self, url: str = "https://mail.163.com/", account:str = 'yt18755284453', password:str = 'mymymy19961779'):
        "利用账号和密码登录，可能需要验证，用cookie登录用self.driver._login"
        if not account or not password:
            self.log.error("no account or password 登录失败")
            return
        
        try:
            
            self.driver.get(url)
            time.sleep(5)
            
            self.driver.switch_to_frame(XPATH="//iframe[contains(@id, 'x-URS-iframe')]")
            time.sleep(1)

            # 账号密码登录
            self.driver.search_and_click(XPATH="//input[@name='email']", waiting_time=1.0)
            time.sleep(2)
            self.driver.send_content(XPATH="//input[@name='email']", content = account)
            time.sleep(2)
            self.driver.search_and_click(XPATH="//input[@name='password']", waiting_time=1.0)
            time.sleep(2)
            self.driver.send_content(XPATH="//input[@name='password']", content = password)
            time.sleep(2)
            self.driver.search_and_click(XPATH="//a[@id='dologin']", waiting_time=1.0)
            time.sleep(5)  # 等待加载验证面板

            # 验证码截图，如果是滑动验证，都是需要两个截图，可用同样的路径
            os.makedirs('./screen_pictures/',exist_ok=True)
            all_img_path = './screen_pictures/163email_screenshot.png'
            captcha_img_path = './screen_pictures/163email_yanzhengma.png'

            # 调用验证函数
            self.handle_captcha(all_img_path=all_img_path,captcha_img_path=captcha_img_path)

            self.log.info("邮箱登录成功")
            time.sleep(5)
            self.driver.driver.switch_to.default_content()#之前跳入iframe，之后就必须跳出

        except:
            self.log.error("登录失败")


    def get_verify_code(self,account:str = 'yt18755284453', password:str = 'mymymy19961779'):
        "获取验证码"
        try:
            
            self.login(account=account, password=password)
            self.driver.search_and_click(XPATH="//span[text()='收 信']", waiting_time=1.0)#点击收件箱
            self.log.info("点击收件箱")
            time.sleep(1)
            self.driver.search_and_click(XPATH="//div[@class='rF0 kw0 nui-txt-flag0']", waiting_time=1.0)#点击第一封未读邮件
            self.log.info("点击第一封邮件")
            time.sleep(5)
            self.driver.switch_to_frame(XPATH="//iframe[contains(@id, 'frameBody')]")#切换到邮件内容的iframe
            self.log.info("切换到邮件内容的iframe")
            content = self.driver.search_and_get_content(xpath="//div[@id='content']")#获取邮件内容
            self.log.info("获取邮件内容")
            code_list = re.split('\n',content)
            for code_item in code_list[:-2]:
                if len(code_item) <= 8:
                    code = code_item
                    break
            # code = re.search(r'\b[a-zA-Z0-9]{4,6}\b',content[:10])#提取验证码
            self.driver.close()
            self.log.info(f"验证码为：{code}")
            return code
        except:
            self.log.error("获取验证码失败")
            return 


    def get_excel(self,account:str = 'yt18755284453', password:str = 'mymymy19961779'):
        "获取excel"
        try:
            self.login(account=account, password=password)
            self.driver.search_and_click(XPATH="//span[text()='收 信']", waiting_time=1.0)#点击收件箱
            self.log.info("点击收件箱")
            time.sleep(1)
            self.driver.search_and_click(XPATH="//span[contains(text(),'投诉')]", waiting_time=1.0)#点击第一封未读邮件
            self.log.info("点击包含投诉的邮件")
            time.sleep(5)
            # self.driver.switch_to_frame(XPATH="//iframe[contains(@id, 'frameBody')]")#切换到邮件内容的iframe
            # self.log.info("切换到邮件内容的iframe")
            
            excel_name = self.driver.find_xpath(XPATH="//strong[@class='dh0']").text#获取下载文件名
            time.sleep(5)
            if os.path.exists(f"C:/Users/24402/Downloads/{excel_name}"):
                return excel_name
            downloadurl = self.driver.find_xpath(XPATH="//a[@target='downloadFrame']").get_attribute("href")#获取下载链接
            self.driver.get(downloadurl)#下载
            self.log.info("点击下载")
            while not os.path.exists(f"C:/Users/24402/Downloads/{excel_name}"):
                time.sleep(2)
            self.driver.close()
            self.log.info("下载成功")
            return excel_name
        except:
            self.log.error("下载失败")
            return


    def slider_image_captcha(self,bg_img_path:str,slider_img_path:str):
        '''
        滑动滑块进行图像验证
        
        参数：
            - bg_img_path(str)：背景图（带凹槽，不带滑块）的存储路径
            - slider_img_path(str)：滑块图的存储路径
        返回： None
        '''

        self.driver.search_and_click(XPATH='//span[text()="请完成安全验证"]', waiting_time=1.0)
        # 获取背景图的链接
        image1_path = self.driver.find_xpath(XPATH='//img[@alt="验证码背景"]').get_attribute('src')
        # 下载背景图
        self.driver.download_image(image1_path,bg_img_path)
        time.sleep(1)
        # 获取背景图的渲染尺寸
        rendered_width = self.driver.find_xpath(XPATH='//img[@alt="验证码背景"]').size['width']
        # 获取滑块图的链接
        image2_path = self.driver.find_xpath(XPATH='//img[@alt="验证码滑块"]').get_attribute('src')
        self.driver.download_image(image2_path,slider_img_path)
        time.sleep(1)

        # 计算背景图中滑块的位置坐标，绘制出来是一个长方形框，选取左上角的坐标点作为偏移量
        # 加载图像
        image = cv2.imread(bg_img_path)  
        slider = cv2.imread(slider_img_path)  
        if image is None:
            self.log.error("加载验证码截图时发生错误")
        # 获取背景图的真实尺寸
        intrinsic_width = image.shape[1]
        # 计算缩放因子
        scale = rendered_width/intrinsic_width
        
        # 转换为灰度图像
        image_gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        slider_gray = cv2.cvtColor(slider, cv2.COLOR_BGR2GRAY)
        # 使用高斯滤波去噪
        image_blur = cv2.GaussianBlur(image_gray, (5, 5), 0)
        slider_blur = cv2.GaussianBlur(slider_gray, (5, 5), 0)

        # 使用边缘检测
        edges_image = cv2.Canny(image_blur, 50, 150)
        edges_slider = cv2.Canny(slider_blur, 50, 150)

        # 执行模板匹配
        result = cv2.matchTemplate(edges_image, edges_slider, cv2.TM_CCOEFF_NORMED)

        # 获取匹配结果中最好的匹配位置
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)

        # 选取左上角的位置，top_left是tuple类型（x,y）
        top_left = max_loc
        
        # 滑块元素
        slider_element = self.driver.find_xpath("//div[contains(@class,'yidun_slider')]")
        # print('位置是：',top_left)

        # 偏移量
        x_offset = top_left[0]*0.95 
        self.driver.move_to_gap(slider_element=slider_element,x_offset=x_offset)



    # 进行滑动验证/顺序点击验证
    def handle_captcha(self,all_img_path:str,captcha_img_path:str):
        '''
        根据不同的验证类型，分别执行滑动验证和顺序点击验证
        
        参数：
            -all_img_path：背景图/整个屏幕的截图
            -captcha_img_path：滑块拼图/验证码整体截图
        '''
        # time.sleep(10)  #
        while True:  
            try:
                self.driver.find_xpath(XPATH='//span[text()="请完成安全验证"]')
                time.sleep(1)
                self.log.info('图像滑动验证/点击验证面板已经出现')

                # 判断是哪种图像验证
                text = self.driver.find_xpath(XPATH='//div[@class="yidun_tips__content"]').text
                self.log.info(f'验证类型是:{text}')

                if text == '向右拖动滑块填充拼图':
                    # 滑动图像验证
                    self.slider_image_captcha(bg_img_path=all_img_path, slider_img_path=captcha_img_path)
                    time.sleep(5)
                    # 可能还会存在滑动验证
                    try:
                        self.driver.find_xpath(XPATH='//span[text()="请完成安全验证"]')
                        self.log.info('滑动验证未完成，重新尝试')
                        continue  #继续循环
                    except Exception as e:
                        # 滑动验证成功，结束循环
                        self.log.info('滑动验证成功')
                        break
                else:   #text == "请依次点击"  # 顺序点击3个图标进行图像验证
                    # 获取整个页面
                    self.driver.driver.save_screenshot(all_img_path)
                    screenshot_img = Image.open(all_img_path)

                    # 验证码div
                    yidun_div = self.driver.find_xpath(XPATH='//div[contains(@class,"yidun--size-small")]') 
                    x_yidun = yidun_div.location.get('x')   
                    y_yidun = yidun_div.location.get('y')  
                    height = yidun_div.size.get('height')   
                    width = yidun_div.size.get('width')
            
                    # 根据坐标获取需要截图的区域（左上x,左上y,右下x，右下y）
                    cropped_img = screenshot_img.crop((x_yidun, y_yidun, x_yidun + width, y_yidun + height))  
                    # 验证码保存为图像
                    cropped_img.save(captcha_img_path)
                    self.log.info('验证码截图保存成功')

                    # 使用超级鹰来获取验证码坐标
                    chaojiying_obj = Chaojiying_Client(username='shiyishi',password='1234@qwer',soft_id='962381')   # 超级鹰用户名、密码、软件ID
                    with open(captcha_img_path, 'rb') as f:
                        im = f.read()
                    data = chaojiying_obj.PostPic(im=im, codetype=9103)  # codetype是识别验证码的方类型，9103是返回三个坐标值
                    print('超级鹰返回的结果：',data) 
                    
                    # 获取输出的3个坐标值
                    position_list = data['pic_str'].split('|')
            
                    # 点击相应的位置
                    for position in position_list:
                        position = position.split(',')      # 变成list
                        x = int(position[0])-width/2        # 以左上角为原点开始计算偏移量，减去half_width
                        y = int(position[1])-height/2        # 减去half_height
                        self.driver.click_image(y_yidun,x,y)  # 根据坐标点击相应位置
                    self.log.info('三个图标已经点击完成')
                    break  # 结束掉循环

            except Exception as e:
                self.log.info('不存在图像滑动验证/点击验证面板')
                time.sleep(1)  # 等待一段时间后重试
                break  # 结束循环


class FirstmailBot():
    def __init__(self, log_path: str = "./logs/email/email_log.log"):
        """
        初始化OutlookBot类的实例。

        参数：
        - log_path：日志文件路径

        返回值：
        无
        """
        super().__init__()
        self.driver = WebDriver(log_path=log_path)
        self.log = logger(filename=log_path)

    def login(self, url: str = "https://firstmail.ltd/ru-RU/webmail/login", account=None,password=None):
        self.driver.get(url)

        time.sleep(10)
        self.log.info("打开邮箱")
        self.driver.send_content(XPATH="//input[@placeholder='support@firstmail.ru']",content=account)#输入账户
        self.log.info("输入账号")
        time.sleep(1)
        self.driver.send_content(XPATH="//input[@aria-describedby='password']",content=password)#输入密码
        self.log.info("输入密码")
        time.sleep(5)
        self.driver.search_and_click(XPATH="//button[@class='btn btn-primary w-100']", waiting_time=1.0)#点击登录
        time.sleep(5)
        self.log.info("点击登录")
        time.sleep(5)
        self.driver.swith_to_new_window(-1)#切换到新窗口
        
        self.driver.search_and_click(XPATH="//input[@name='loginfmt']", waiting_time=1.0)
        self.driver.send_content(XPATH="//input[@name='loginfmt']", content = account)
        self.log.info("输入账号")
        time.sleep(1)
        self.driver.search_and_click(XPATH="//button[@type='submit']", waiting_time=1.0)
        self.log.info("点击下一步")
        time.sleep(5)
        self.driver.search_and_click(XPATH="//input[@name='passwd']", waiting_time=1.0)
        self.driver.send_content(XPATH="//input[@name='passwd']", content = password)
        self.log.info("输入密码")
        time.sleep(1)
        self.driver.search_and_click(XPATH="//button[@type='submit']", waiting_time=1.0)
        self.log.info("点击登录")

    def get_verify_code(self,account=None,password=None):
        self.login(account=account,password=password)
        time.sleep(10)
        self.driver.search_and_click(XPATH="//li[@class='email-list-item d email-border email-read']", waiting_time=5.0)
        self.log.info("点击第一个未读邮件")
        self.driver.switch_to_frame(XPATH="//iframe[@frameborder='0']")#切换到邮件内容的iframe
        #切换到document
        self.log.info("切换到邮件内容的iframe")
        time.sleep(5)
        code = self.driver.find_xpath(XPATH="//td[@class='h1 black']").text
        self.log.info("验证码为：{}".format(code))
        self.driver.close()
        
        return code

        #smsactivate密钥：477c648Af2b7c0A37c3c69843f85AbA6





 


# class OutlookBot():
#     def __init__(self, log_path: str = "./logs/email/email_log.log"):
#         """
#         初始化OutlookBot类的实例。

#         参数：
#         - log_path：日志文件路径

#         返回值：
#         无
#         """
#         super().__init__()
#         self.driver = WebDriver(log_path=log_path)
#         self.log = logger(filename=log_path)

#     def login(self, url: str = "https://outlook.live.com/mail/0/inbox", account=None,password=None):
#         self.driver.get(url)
#         pdb.set_trace()
#         time.sleep(10)
#         self.log.info("打开邮箱")
#         self.driver.find_xpaths(XPATH="//a[@data-bi-ecn='Sign in']")[-2].click()
        
#         #点击登录
#         # self.driver.search_and_click(XPATH="//a[@data-bi-ecn='Sign in']", waiting_time=1.0)#点击登录
#         time.sleep(5)
#         self.log.info("点击登录")
#         self.driver.swith_to_new_window(-1)#切换到新窗口
        
#         self.driver.search_and_click(XPATH="//input[@name='loginfmt']", waiting_time=1.0)
#         self.driver.send_content(XPATH="//input[@name='loginfmt']", content = account)
#         self.log.info("输入账号")
#         time.sleep(1)
#         self.driver.search_and_click(XPATH="//button[@type='submit']", waiting_time=1.0)
#         self.log.info("点击下一步")
#         time.sleep(5)
#         self.driver.search_and_click(XPATH="//input[@name='passwd']", waiting_time=1.0)
#         self.driver.send_content(XPATH="//input[@name='passwd']", content = password)
#         self.log.info("输入密码")
#         time.sleep(1)
#         self.driver.search_and_click(XPATH="//button[@type='submit']", waiting_time=1.0)
#         self.log.info("点击登录")
#         # if account.endswith("@hotmail.com"):
#         #     self.driver.search_and_click(XPATH="//button[@type='submit']", waiting_time=1.0)
#         #     self.log.info("点击下一步")
#         # else:
#         #     self.driver.search_and_click(XPATH="//button[@type='submit']", waiting_time=1.0)
#         #     self.log.info("点击登录")
#         try:
#             self.driver.search_and_click(XPATH="//button[@type='submit']", waiting_time=1.0)
#             self.log.info("点击下一步")
#         except:
#             self.log.info("没有下一步")
       
#         tmp_element = self.driver.find_xpaths(XPATH="//div[contains(text(),'帐户已锁定')]")
#         if tmp_element:
#             self.log.info("帐户已锁定")
#             self.driver.search_and_click(XPATH="//button[@aria-describedby='serviceAbuseLandingTitle serviceAbuseDescription']", waiting_time=1.0)
#             self.log.info("点击继续")
#             time.sleep(2)
#             self.driver.search_and_click(XPATH="//option[@value='CO']", waiting_time=1.0) 
#             self.log.info("点击国家/地区") 
#             time.sleep(2)
#             # pdb.set_trace()
#             number = self.get_phone()
#             self.driver.send_content(XPATH="//input[@id='proofField']", content = number)
#             self.log.info("输入手机号:{}".format(number))
#             time.sleep(2)

#             self.driver.search_and_click(XPATH="//button[@id='nextButton']", waiting_time=1.0)
#             try:
#                 self.driver.search_and_click(XPATH="//div[@id='SmsBlockTitle']", waiting_time=1.0)
#                 self.log.info("尝试次数过多，需要用其他方式验证，跳过，当前账号为：{}".format(account))
#                 return
#             except:
#                 self.log.info("没有尝试次数过多，可以继续获取短信")
#             time.sleep(20)
#             code = self.get_sms_code()
#             self.log.info("获取验证码:{}".format(code))
#             self.driver.search_and_click(XPATH="//input[@id='enter-code-input']", waiting_time=1.0)
#             self.driver.send_content(XPATH="//input[@id='enter-code-input']", content = code)
#             self.log.info("输入验证码")
#             time.sleep(2)
#             self.driver.search_and_click(XPATH="//button[@id='nextButton']", waiting_time=1.0)
#             self.log.info("点击下一步")

#         try:
#             self.driver.search_and_click(XPATH="//button[@type='submit']", waiting_time=1.0)
#             self.log.info("已取消阻止账户，点击继续")
#         except:
#             self.log.info("没有阻止账户")
#         try:
#             self.driver.search_and_click(XPATH="//a[@id='iShowSkip']", waiting_time=1.0)
#             self.log.info("点击跳过添加备用邮箱")
#             # self.driver.search_and_click(XPATH="//button[@type='submit']", waiting_time=1.0)
#             # self.log.info("点击下一步")
#         except:
#             self.log.info("没有添加备用邮箱")
#         try:
#             self.driver.search_and_click(XPATH="//a[@id='iShowSkip']", waiting_time=1.0)
#             self.log.info("点击跳过添加备用邮箱")
#         except:
#             self.log.info("没有第二遍添加备用邮箱按钮")
#         try:
#             self.driver.search_and_click(XPATH="//button[@id='declineButton']", waiting_time=1.0)
#             self.log.info("点击取消保持登录状态")
#         except:
#             self.log.info("没有保持登录状态")
    
#     def get_phone(self):
#         #请求号码
#         url = "https://api.sms-activate.io/stubs/handler_api.php?api_key=477c648Af2b7c0A37c3c69843f85AbA6&action=getActiveActivations"
#         response = requests.get(url).json()
#         self.log.info("获取的号码信息为：{}".format(response))
#         if response["status"] == "success":
#             self.log.info("当前手机号有效")
#             phone = response["activeActivations"][0]['phoneNumber'][2:]
#         else:
#             #{"status":"error","error":"NO_ACTIVATIONS"}
#             self.log.info("需要购买新号码")
#             url = 'https://api.sms-activate.io/stubs/handler_api.php?api_key=477c648Af2b7c0A37c3c69843f85AbA6&action=getNumber&service=mm&forward=0&country=33&maxPrice=20&activationType=0&language=cmn-Hans-CN&userId=8315287'
#             response = requests.get(url).text
#             #ACCESS_NUMBER:2890988871:573188857701
#             phone_number = response.split(":")[-1]
#             phone = phone_number[2:]
#         return phone

#     def get_sms_code(self):
#         #获取短信验证码
#         #{"status":"success","activeActivations":[{"activationId":"2890928091","serviceCode":"mm","phoneNumber":"573169215240","activationCost":"10.00","activationStatus":"2","activationTime":"2024-10-1510:08:52","discount":"0","repeated":"0","countryCode":"33","countryName":"Colombia","canGetAnotherSms":"1","smsCode":"8932","smsText":"8932是 Microsoft 帐户验证码"}]}
#         url = "https://api.sms-activate.io/stubs/handler_api.php?api_key=477c648Af2b7c0A37c3c69843f85AbA6&action=getActiveActivations"
#         response = requests.get(url).json()
#         code = response["activeActivations"][0]['smsCode']
#         return code

#     def get_verify_code(self,account=None,password=None):
#         self.login(account=account,password=password)
#         time.sleep(10)
#         try:
#             self.driver.search_and_click(XPATH="//button[@class='fui-Button r1alrhcs']", waiting_time=1.0)
#             self.log.info("点击关闭广告")
#         except:
#             self.log.info("没有广告")
#         self.driver.search_and_click(XPATH="//div[@class='jGG6V gDC9O']", waiting_time=1.0)
#         self.driver.search_and_click(XPATH="//div[@class='jGG6V gDC9O']", waiting_time=1.0)
#         self.log.info("点击第一封未读邮件")
#         time.sleep(5)
#         code = self.driver.find_xpath(XPATH="//td[@class='x_h1 x_black']").text
#         self.log.info("验证码为：{}".format(code))
#         self.driver.close()
        
#         return code

#         #smsactivate密钥：477c648Af2b7c0A37c3c69843f85AbA6



#     def send_email(self,target_email:str,content:str=None,subject:str=None):
#         '''
#         发送邮件
#         target_email: str, 目标邮箱
#         subject: str, 邮件主题
#         content:  str 邮件内容
#         '''
#         try:
#             # 登录成功之后刷新页面
#             self.driver.driver.refresh()
#             time.sleep(random.uniform(5,10))
#             self.log.info(f'点击 New mail 按钮')
#             self.driver.search_and_click(XPATH='//button[@aria-label="New mail"]', waiting_time=random.uniform(3,7))
#             self.log.info(f'输入收件人邮箱：{target_email}')
#             self.driver.search_and_click(XPATH='//div[@role="textbox" and @aria-label="To"]',waiting_time=1.0)
#             self.driver.send_content(XPATH='//div[@role="textbox" and @aria-label="To"]', content=target_email)
#             time.sleep(random.uniform(2,5))
#             try:
#                 self.driver.search_and_click(XPATH='//div[contains(text(),"Use this address:")]',waiting_time=2.0)
#             except:
#                 pass
#             if subject:
#                 self.log.info(f'输入邮件主题：{subject}')
#                 self.driver.search_and_click(XPATH='//input[@type="text" and @placeholder="Add a subject" and @aria-label="Subject"]',waiting_time=1.0)
#                 self.driver.send_content(XPATH='//input[@type="text" and @placeholder="Add a subject" and @aria-label="Subject"]', content=subject)
#                 time.sleep(random.uniform(2,5))
#             if content:
#                 self.log.info(f'输入邮件内容：{content}')
#                 self.driver.search_and_click(XPATH='//div[@role="textbox" and @aria-label="Message body"]',waiting_time=1.0)
#                 self.driver.send_content(XPATH='//div[@role="textbox" and @aria-label="Message body"]', content=content)
#                 time.sleep(random.uniform(2,5))
#             self.log.info(f'点击 Send 按钮')
#             self.driver.search_and_click(XPATH='//button[@aria-label="Send"]',waiting_time=1.0)
#             time.sleep(random.uniform(2,5))
#             self.log.info(f'邮件发送成功')
#         except Exception as e:
#             self.log.error("发送邮件失败：{}".format(e))



