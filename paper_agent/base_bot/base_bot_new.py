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
import zipfile



class WebDriver():
    """用selenium网页模拟实现的一些基本功能"""    
    def __init__(self, log_path,driver_path: str = DEFAULT_DRIVER_PATH,ip=None,username=None,password=None,use_proxy=False) -> None:
        self.cookies = None
        ser = Service(driver_path)
        chrome_options = webdriver.ChromeOptions()
        # #为Chrome配置无头模式
        # chrome_options.add_argument("--headless")  
        # chrome_options.add_argument('--no-sandbox')
        # chrome_options.add_argument('--disable-gpu')
        # chrome_options.add_argument('--disable-dev-shm-usage')
        # # 在启动浏览器时加入配置
        # dr = webdriver.Chrome(options=chrome_options)
        # 把允许提示这个弹窗关闭
        prefs = {"profile.default_content_setting_values.notifications": 2}
        chrome_options.add_experimental_option("prefs", prefs)
        chrome_options.add_argument("-ignore-certificate-errors") #忽略证书
        chrome_options.add_argument("-ignore -ssl-errors") #忽略ssl错误
        chrome_options.add_argument("--disable-blink-features=AutomationControlled") #防止被识别为机器人
        chrome_options.add_experimental_option("excludeSwitches", ['enable-automation'])  # 去掉顶部自动测试提示语
        # chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])
        # 添加浏览器请求header
        user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36'
        chrome_options.add_argument(f'--user-agent={user_agent}')
        
        if ip: # ip是城市
            chrome_options.add_argument("--start-maximized")
            # 根据ip获取IP 和 port
            ip_port = get_ip_port(ip=ip)
            if ip_port:
                proxyauth_plugin_path = create_proxyauth_extension(
                    proxy_host=ip_port["ip"],
                    proxy_port=ip_port["port"],
                    proxy_username=username,
                    proxy_password=password
                )
                chrome_options.add_extension(proxyauth_plugin_path)
                
        if use_proxy:
            # Bright Data Proxy Configuration
            # http://brd-customer-hl_3d1d97f5-zone-residential_proxy1-country-tw-city-changhua:2e51vrq5ypu6@brd.superproxy.io:33335
            proxy_host = "brd.superproxy.io"
            proxy_port = 33335  # Replace with your port number
            proxy_user = "brd-customer-hl_3d1d97f5-zone-datacenter_proxy1"  # Replace with your Bright Data username
            proxy_pass = "90an3t580fl2"
            # Full Proxy URL
            # proxy = f"http://{proxy_username}:{proxy_password}@{proxy_host}:{proxy_port}"
            # chrome_options.add_argument(f"--proxy-server={proxy}")
            # 创建代理插件
            manifest_json = """
            {
                "version": "1.0.0",
                "manifest_version": 2,
                "name": "Chrome Proxy",
                "permissions": [
                    "proxy",
                    "tabs",
                    "unlimitedStorage",
                    "storage",
                    "<all_urls>",
                    "webRequest",
                    "webRequestBlocking"
                ],
                "background": {
                    "scripts": ["background.js"]
                }
            }
            """

            background_js = f"""
            var config = {{
                    mode: "fixed_servers",
                    rules: {{
                    singleProxy: {{
                        scheme: "http",
                        host: "{proxy_host}",
                        port: parseInt({proxy_port})
                    }},
                    bypassList: ["localhost"]
                    }}
            }};
            chrome.proxy.settings.set({{value: config, scope: "regular"}}, function() {{}});
            chrome.webRequest.onAuthRequired.addListener(
                    function(details) {{
                        return {{
                            authCredentials: {{
                                username: "{proxy_user}",
                                password: "{proxy_pass}"
                            }}
                        }};
                    }},
                    {{urls: ["<all_urls>"]}},
                    ['blocking']
            );
            """
            # 写入插件文件
            plugin_file = 'proxy_auth_plugin.zip'
            with zipfile.ZipFile(plugin_file, 'w') as zp:
                zp.writestr("manifest.json", manifest_json)
                zp.writestr("background.js", background_js)
            chrome_options.add_extension(plugin_file)
        else:
            chrome_options.add_argument('--proxy-server="direct://"')
            chrome_options.add_argument('--proxy-bypass-list=*')  # 忽略所有代理
        
        self.driver = webdriver.Chrome(service=ser,options=chrome_options)
        self.driver.maximize_window()  # 设置页面最大化，避免元素被隐藏
        #设置log
        # log_path = os.path.join(os.path.dirname(__file__), "log\\webdriver.log")
        self.log = logger(filename=log_path)

    import zipfile

    def create_proxy_auth_extension(self,proxy_host, proxy_port, proxy_user, proxy_pass, scheme='http',
                                    plugin_path='proxy_auth_plugin.zip'):
        """创建带代理认证信息的 Chrome 插件 zip 文件"""
        manifest_json = """
        {
            "version": "1.0.0",
            "manifest_version": 2,
            "name": "Proxy Auth Extension",
            "permissions": [
                "proxy", "tabs", "unlimitedStorage", "storage", "<all_urls>", "webRequest", "webRequestBlocking"
            ],
            "background": {
                "scripts": ["background.js"]
            },
            "minimum_chrome_version":"22.0.0"
        }
        """

        background_js = f"""
        var config = {{
            mode: "fixed_servers",
            rules: {{
                singleProxy: {{
                    scheme: "{scheme}",
                    host: "{proxy_host}",
                    port: parseInt({proxy_port})
                }},
                bypassList: ["localhost"]
            }}
        }};
        
        chrome.proxy.settings.set({{value: config, scope: "regular"}}, function() {{}});

        chrome.webRequest.onAuthRequired.addListener(
            function(details, callbackFn) {{
                callbackFn({{
                    authCredentials: {{
                        username: "{proxy_user}",
                        password: "{proxy_pass}"
                    }}
                }});
            }},
            {{urls: ["<all_urls>"]}},
            ['blocking']
        );
        """

        with zipfile.ZipFile(plugin_path, 'w') as zp:
            zp.writestr("manifest.json", manifest_json)
            zp.writestr("background.js", background_js)

        return plugin_path

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
            if token:
                self.driver.add_cookie({
    'name': 'auth_token',  # Twitter 使用的 token 名称
    'value': token,
    'domain': '.x.com'
})
            time.sleep(5)
            self.driver.get(url=url)
            self.log.info("cookies加载成功，进入主页")
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



