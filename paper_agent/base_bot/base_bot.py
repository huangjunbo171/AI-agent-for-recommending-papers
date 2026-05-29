import os
import sys
pythonpath = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
# sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
sys.path.insert(0,pythonpath)
import selenium
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
import time
import requests
import json
import os
from PIL import Image
from selenium.common.exceptions import NoSuchElementException
from utils.log import logger
from config import DEFAULT_DRIVER_PATH
from utils.proxy import create_proxyauth_extension,get_ip_port
from selenium import webdriver
from selenium.webdriver import ActionChains
from config import MIMN_IP
import random

class WebDriver():
    """用selenium网页模拟实现的一些基本功能"""    
    @staticmethod
    def get_chrome_options(
        fingerprint:dict  = None,
        headless: bool = False,
        ip: str = None,
        username: str = None,
        password: str = None,
        use_proxy: bool = False
    ) -> webdriver.ChromeOptions:
        """
        生成统一的 Chrome 配置选项
        
        Args:
            fingerprint: 指纹信息，包含 user-agent 等配置
            language: 接受语言，默认 "en-US,en;q=0.9"
            headless: 无头模式，默认 False
            ip: 城市 IP（来自 config.py 的 CITY_INFO），用于天启代理
            username: 代理用户名
            password: 代理密码
            use_proxy: 是否使用内置代理 (MIMN_IP)
        
        Returns:
            配置好的 WebDriver.ChromeOptions 对象
        """
        options = webdriver.ChromeOptions()
        
        # 无头模式配置
        if headless:
            options.add_argument("--headless")
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-gpu')
            options.add_argument('--disable-dev-shm-usage')
        
        
        # 通知和证书配置
        prefs = {"profile.default_content_setting_values.notifications": 2}
        options.add_experimental_option("prefs", prefs)
        options.add_argument("--ignore-certificate-errors")
        options.add_argument("--ignore-ssl-errors")
        
        # 反爬虫和自动化检测配置
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ['enable-automation', 'enable-logging'])
        options.add_experimental_option("useAutomationExtension", False)
        
        # 指纹/UA/语言/配置目录 
        user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36'
        language = 'en-US,en;q=0.9'
        if fingerprint:
            # 用户数据目录（多开隔离）
            profile_path = fingerprint.get("profile_path",None)
            if profile_path:
                os.makedirs(profile_path, exist_ok=True)
                options.add_argument(f"--user-data-dir={profile_path}")
            # UserAgent          
            user_agent = fingerprint.get("user_agent") or user_agent
            # 语言
            language = fingerprint.get("languages")[0] if fingerprint.get("languages") else language
        # 配置
        options.add_argument(f"--lang={language}")
        options.add_argument(f'--user-agent={user_agent}')


        # 窗口大小配置
        options.add_argument("--start-maximized")
        # 禁用 WebGL 和音频
        options.add_argument("--disable-webgl")
        options.add_argument("--mute-audio")
        
        # 代理配置 - 天启 IP
        if ip:
            ip_port = get_ip_port(ip=ip)
            if ip_port:
                proxyauth_plugin_path = create_proxyauth_extension(
                    proxy_host=ip_port["ip"],
                    proxy_port=ip_port["port"],
                    proxy_username=username,
                    proxy_password=password
                )
                options.add_extension(proxyauth_plugin_path)
        
        # 代理配置 - 内置代理或直连
        elif use_proxy:
            options.add_argument(f"--proxy-server=http://{MIMN_IP['IP']}:{MIMN_IP['PORT']}")
        else:
            options.add_argument('--proxy-server="direct://"')
            options.add_argument('--proxy-bypass-list=*')
        
        return options
    


    def __init__(
        self, 
        log_path, 
        driver_path: str = DEFAULT_DRIVER_PATH, 
        ip: str = None, 
        username: str= None, 
        password: str=None, 
        use_proxy: bool=False, 
        headless: bool=False,
        fingerprint: dict=None
    ) -> None:
        # 设置 log
        self.log = logger(filename=log_path)

        self.cookies = None
        self.fingerprint = fingerprint
        # 使用 get_chrome_options 生成配置
        chrome_options = self.get_chrome_options(
            fingerprint=self.fingerprint,
            headless=headless,
            ip=ip,
            username=username,
            password=password,
            use_proxy=use_proxy
        )
        
        if driver_path and os.path.isfile(driver_path):
            ser = Service(driver_path)
            self.driver = webdriver.Chrome(service=ser, options=chrome_options)
            self.log.info(f"Using configured chromedriver: {driver_path}")
        else:
            self.driver = webdriver.Chrome(options=chrome_options)
            self.log.info("Configured chromedriver path not found, falling back to Selenium Manager")
        self.driver.maximize_window()  # 设置页面最大化，避免元素被隐藏
        
        # 注入 CDP 脚本，隐藏 webdriver 标记并伪造 navigator 属性
        self.driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": """
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
                Object.defineProperty(navigator, 'platform', {get: () => 'Win32'});
                Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3]});
            """
        })
        
        self.log.info("Chrome 驱动初始化成功")



    
    def get_cookies(self, url: str = None):
        '''获取cookies,直接返回获取的cookie，默认是获取weibo'''
        if not url:
            url = "https://weibo.com/newlogin?tabtype=weibo&gid=102803&openLoginLayer=0&url=https%3A%2F%2Fweibo.com%2F"
        self.driver.get(url)
        time.sleep(10)
        Cookies = self.driver.get_cookies()
        self.log.info("cookies get")
        return Cookies
        


        
    def check_cookies(self, username: str = "",check_url:str = ""):
        "检查cookie有效性 check_url建议为网站主页或用户主页，通过检测网站文本中有无username来判断"
        if self.cookies is None:
            self.log.error("cookies is None")
            return False
        try:
            s = requests.Session()
            for cookie in self.cookies:
                s.cookies.set(cookie["name"], cookie["value"])
            resp = s.get("https://weibo.com")
            html = resp.text
            if username in html:
                return True
            else:
                self.log.error("cookies无效或者与username不匹配")
                return False
        except:
            self.log.error("cookies无效或者与username不匹配")
            return False


    # def _login(self, url: str=None, cookies:list=None):
    #     "把cookie处理好，转到指定界面"
    #     try:
    #         for cookie in cookies:
    #             self.driver.add_cookie(cookie)
    #         self.log.info("添加cookies")
    #         time.sleep(5)
    #         self.driver.get(url=url)
    #         self.log.info("cookies加载结束，进入主页")
    #         time.sleep(5)
    #     except Exception as e:
    #         self.log.error(str(e))
    #         self.log.error("cookies加载失败")
    def _login(self, url: str = "https://weibo.com",cookies:list = None,token:str = None):
        "把cookie处理好，转到指定界面"
        try:
            self.driver.get(url=url)
            self.log.info("进入登录界面")
            time.sleep(5)
            if cookies:
                # cookies = json.loads(cookies)
                for cookie in cookies:
                    self.driver.add_cookie(cookie)
                self.log.info("添加cookies成功")
                time.sleep(random.randint(10,20))
                self.driver.get(url=url)
                self.log.info("cookies加载成功，进入主页")
                time.sleep(random.randint(5,10))
            elif token:
                self.driver.add_cookie({
                    'name': 'auth_token',  # Twitter 使用的 token 名称
                    'value': token,
                    'domain': '.x.com'
                })
                time.sleep(5)
                self.driver.get(url=url)
                self.log.info("token加载成功，进入主页")
                time.sleep(2)
        except Exception as e:
            self.log.error(str(e))
            self.log.error("cookies加载失败")        
    
    def close(self):
        self.driver.close()
        
    def quit(self):
        self.driver.quit()


    def get(self,url):
        self.driver.get(url)
    
    def find_xpath(self,XPATH:str = None):
        return self.driver.find_element(By.XPATH,XPATH)
    
        
    def find_xpaths(self,XPATH:str = None):
        return self.driver.find_elements(By.XPATH,XPATH)

    def send_content(self, XPATH:str = None, content:str = None):
        try:
            self.driver.find_element(By.XPATH,XPATH).send_keys(content)
            time.sleep(0.5)
        except Exception as e:
            self.log.error(str(e))

    
    def scroll(self,size:int = 200):
        "模拟鼠标滚动一次，每次滚动一定距离"
        #for i in range(times):
        #    self.driver.execute_script("window.scrollTo(0,document.body.scrollHeight)")
        #    time.sleep(0.7)

        #original_top = 0
        #while True:
            # 循环下拉滚动条
        self.driver.execute_script(f"window.scrollBy(0,{size})")
        time.sleep(0.5)
            # 获取当前滚动条距离顶部的距离
            #check_height = self.wd.execute_script(
            #    "return document.documentElement.scrollTop || window.pageYOffset || document.body.scrollTop;")
            # 如果滚动条距离上面的距离不再改变，也就是滚动后的距离和之前距离顶部的位置没有改变，说明到达最下方，跳出循环
            #if check_height == original_top:
            #    break
            #original_top = check_height

    def element_to_top(self,XPATH:str = None):
        "将元素滚动到最上面的位置"
        #找到指定元素
        element = self.driver.find_element(By.XPATH,XPATH)
        #获取元素位置
        location = element.location
        #计算滚动距离
        distance = location["y"]
        #滚动
        self.driver.execute_script("arguments[0].scrollIntoView();",distance)
        time.sleep(0.5)
        # elements = self.driver.find_elements(By.XPATH,XPATH)
        # for element in elements:
        #     if element.text == "View all":
        #         self.driver.execute_script("arguments[0].scrollIntoView();",element)
        #         time.sleep(0.5)
        #         break

    def switch_to_frame(self,XPATH:str = None):
        "切换到frame"
        frame = self.driver.find_element(By.XPATH,XPATH)
        self.driver.switch_to.frame(frame)
        time.sleep(0.5)


    def search_and_click(self,XPATH:str = "",waiting_time:float = 0.5,auto_scroll:bool = False):
        "根据XPATH搜索并点击button，主要用于点赞"
        if not XPATH:
            self.log.error("XPATH is None")
            return
        try:
            if not auto_scroll:
                self.driver.find_element(By.XPATH,XPATH).click()
            else:
                # 判断页面是否有当前元素
                times = 0
                while True:
                    try:
                        self.driver.find_element(By.XPATH,XPATH).click()
                        break
                    except:
                        self.scroll()
                        times += 1
                        if times > 2:
                            self.log.error("Try too many times, click failed")
                            raise Exception("Try too many times, click failed")
            time.sleep(waiting_time)
            return
        except Exception as e:
            self.log.error("XPATH not found")
            raise Exception("XPATH not found")
    
    def search_only_bool(self, XPATH: str = "", auto_scroll: bool = False):
        """根据XPATH搜索，主要用于检测是否存在某个元素 用于翻页"""
        try:
            if not auto_scroll:
                self.driver.find_element(By.XPATH, XPATH)
                return True
            else:
                # 判断页面是否有当前元素
                for _ in range(2): # 只滚一次
                    try:
                        self.driver.find_element(By.XPATH, XPATH)
                        return True
                    except:
                        self.scroll()
                self.log.error("Try too many times, search failed")
                return False
        except NoSuchElementException:
            return False
        except Exception as e:
            self.log.error(str(e))
            return False
        
    def send_and_submit(self, xpath_content: str="", xpath_button: str = "", content: str=""):
        '''往xpath_content内容框里输入内容content,并且点击xpath_button发送content'''
        if not xpath_button or not xpath_content:
            self.log.error("xpath_button or xpath_content is None")
            return
        elif not content:
            self.log.error("content is None")
            return
        try:
            self.driver.find_element(By.XPATH,xpath_content).send_keys(content)
            time.sleep(0.5)
            self.driver.find_element(By.XPATH,xpath_button).click()
            time.sleep(0.8)
        except:
            self.log.error("button or content not found")
            raise Exception("button or content not found")
        
    def search_and_get_content(self,xpath:str = ""):
        "根据XPATH搜索并返回文本内容"
        if not xpath:
            self.log.error("xpath is None")
            return
        try:
            return self.driver.find_element(By.XPATH,xpath).text
        except:
            self.log.error("xpath not found")
            raise Exception("xpath not found")

        
    def search_and_get_all_content(self,xpath:str = "",attribute=None)->list[str]:
        "根据XPATH搜索并返回文本内容"
        if not xpath:
            self.log.error("xpath is None")
            return
        try:
            if not attribute:
                temp = self.driver.find_elements(By.XPATH,xpath)
                return [i.text for i in temp]
            else:
                temp = self.driver.find_elements(By.XPATH,xpath)
                return [{"text":i.text,attribute:i.get_attribute(attribute)} for i in temp]
        except:
            self.log.error("xpath not found")
            return
        
    def go_back(self):
        "返回上一个网页"
        self.driver.back()
        time.sleep(1)

    def open_new_tab(self,url:str = ""):
        "打开新标签页"
        self.driver.execute_script(f"window.open('{url}');")
        time.sleep(0.5)
        
        # 图像验证码，根据坐标点击相应位置
    def click_image(self, parent_element, x_offset, y_offset):
        action_chains = ActionChains(self.driver)   # 定义ActionChains 对象
        # 是以parent_element元素的中心位置为原点，这个偏移量可以是负数
        action_chains.move_to_element_with_offset(parent_element,x_offset,y_offset).click().perform()   # 点击相应位置
        time.sleep(2)
        # 重置ActionChains对象，避免坐标累积
        action_chains.reset_actions()
        time.sleep(1)    

        
    def judge_bottom(self):
        "判断是否到达页面底部"
        js = "return document.documentElement.scrollTop + window.innerHeight >= document.documentElement.scrollHeight"
        return self.driver.execute_script(js)
    
    def swith_to_new_window(self,id):
        "切换到新窗口"
        self.driver.switch_to.window(self.driver.window_handles[id])


    def switch_to_iframe(self,id):
        "通过索引切换到iframe"
        self.driver.switch_to.frame(id)



