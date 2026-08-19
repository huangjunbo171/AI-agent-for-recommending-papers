import json
import os
import random
import shutil
import sys
import time

import requests
import selenium
from PIL import Image
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException, WebDriverException
from selenium.webdriver import ActionChains
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By

pythonpath = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, pythonpath)

from config import DEFAULT_DRIVER_PATH, MIMN_IP
from utils.log import logger
from utils.proxy import create_proxyauth_extension, get_ip_port


class WebDriver:
    """Selenium browser wrapper used by the project."""

    @staticmethod
    def _infer_platform_from_user_agent(user_agent: str) -> str:
        ua = (user_agent or "").lower()
        if "macintosh" in ua or "mac os x" in ua:
            return "MacIntel"
        if "linux" in ua:
            return "Linux x86_64"
        return "Win32"

    @classmethod
    def _normalize_fingerprint(cls, fingerprint: dict = None) -> dict:
        if not fingerprint:
            return None

        normalized = dict(fingerprint)
        profile_path = normalized.get("profile_path")
        if profile_path:
            normalized["profile_path"] = os.path.abspath(profile_path)

        normalized["platform"] = cls._infer_platform_from_user_agent(normalized.get("user_agent"))
        normalized["languages"] = normalized.get("languages") or ["en-US", "en"]
        normalized["plugins"] = normalized.get("plugins") or [1, 2, 3]
        normalized["timezone"] = normalized.get("timezone") or "America/New_York"
        normalized["device_pixel_ratio"] = normalized.get("device_pixel_ratio") or 1
        normalized["hardware_concurrency"] = normalized.get("hardware_concurrency") or 4
        return normalized

    @staticmethod
    def _cleanup_profile_artifacts(profile_path: str, log=None) -> None:
        if not profile_path or not os.path.isdir(profile_path):
            return

        stale_entries = {
            "SingletonLock",
            "SingletonSocket",
            "SingletonCookie",
            "DevToolsActivePort",
        }
        for entry_name in stale_entries:
            entry_path = os.path.join(profile_path, entry_name)
            if not os.path.exists(entry_path):
                continue
            try:
                if os.path.isdir(entry_path):
                    shutil.rmtree(entry_path, ignore_errors=True)
                else:
                    os.remove(entry_path)
            except Exception as e:
                if log:
                    log.info(f"Failed to cleanup Chrome profile artifact {entry_path}: {e}")

    @staticmethod
    def get_chrome_options(
        fingerprint: dict = None,
        headless: bool = False,
        ip: str = None,
        username: str = None,
        password: str = None,
        use_proxy: bool = False
    ) -> webdriver.ChromeOptions:
        options = webdriver.ChromeOptions()

        if headless:
            options.add_argument("--headless=new")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-gpu")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--window-size=1920,1080")

        prefs = {"profile.default_content_setting_values.notifications": 2}
        options.add_experimental_option("prefs", prefs)
        options.add_argument("--ignore-certificate-errors")
        options.add_argument("--ignore-ssl-errors")

        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
        options.add_experimental_option("useAutomationExtension", False)
        options.add_argument("--remote-debugging-port=0")
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")
        options.add_argument("--disable-background-networking")
        options.add_argument("--disable-renderer-backgrounding")
        options.add_argument("--disable-features=Translate,OptimizationHints,MediaRouter")

        user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36"
        )
        language = "en-US,en;q=0.9"
        if fingerprint:
            profile_path = fingerprint.get("profile_path")
            if profile_path:
                os.makedirs(profile_path, exist_ok=True)
                options.add_argument(f"--user-data-dir={profile_path}")
            user_agent = fingerprint.get("user_agent") or user_agent
            language = fingerprint.get("languages")[0] if fingerprint.get("languages") else language

        options.add_argument(f"--lang={language}")
        options.add_argument(f"--user-agent={user_agent}")
        options.add_argument("--start-maximized")
        options.add_argument("--disable-webgl")
        options.add_argument("--mute-audio")

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
        elif use_proxy:
            options.add_argument(f"--proxy-server=http://{MIMN_IP['IP']}:{MIMN_IP['PORT']}")
        else:
            options.add_argument('--proxy-server="direct://"')
            options.add_argument("--proxy-bypass-list=*")

        return options

    def __init__(
        self,
        log_path,
        driver_path: str = DEFAULT_DRIVER_PATH,
        ip: str = None,
        username: str = None,
        password: str = None,
        use_proxy: bool = False,
        headless: bool = False,
        fingerprint: dict = None
    ) -> None:
        self.log = logger(filename=log_path)
        self.cookies = None
        self.fingerprint = self._normalize_fingerprint(fingerprint)

        profile_path = self.fingerprint.get("profile_path") if self.fingerprint else None
        if profile_path:
            self._cleanup_profile_artifacts(profile_path, log=self.log)

        chrome_options = self.get_chrome_options(
            fingerprint=self.fingerprint,
            headless=headless,
            ip=ip,
            username=username,
            password=password,
            use_proxy=use_proxy
        )

        if driver_path and os.path.isfile(driver_path):
            service = Service(driver_path)
            self.driver = webdriver.Chrome(service=service, options=chrome_options)
            self.log.info(f"Using configured chromedriver: {driver_path}")
        else:
            self.driver = webdriver.Chrome(options=chrome_options)
            self.log.info("Configured chromedriver path not found, falling back to Selenium Manager")

        if headless:
            self.driver.set_window_size(1920, 1080)
        else:
            self.driver.maximize_window()

        script_languages = (self.fingerprint or {}).get("languages") or ["en-US", "en"]
        script_platform = (self.fingerprint or {}).get("platform") or "Win32"
        script_plugins = (self.fingerprint or {}).get("plugins") or [1, 2, 3]
        script_hardware = (self.fingerprint or {}).get("hardware_concurrency") or 4
        script_device_ratio = (self.fingerprint or {}).get("device_pixel_ratio") or 1
        self.driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {
                "source": f"""
                    Object.defineProperty(navigator, 'webdriver', {{get: () => undefined}});
                    Object.defineProperty(navigator, 'languages', {{get: () => {json.dumps(script_languages)}}});
                    Object.defineProperty(navigator, 'platform', {{get: () => {json.dumps(script_platform)}}});
                    Object.defineProperty(navigator, 'plugins', {{get: () => {json.dumps(script_plugins)}}});
                    Object.defineProperty(navigator, 'hardwareConcurrency', {{get: () => {json.dumps(script_hardware)}}});
                    Object.defineProperty(window, 'devicePixelRatio', {{get: () => {json.dumps(script_device_ratio)}}});
                """
            }
        )

        timezone = (self.fingerprint or {}).get("timezone")
        if timezone:
            try:
                self.driver.execute_cdp_cmd("Emulation.setTimezoneOverride", {"timezoneId": timezone})
            except Exception as e:
                self.log.info(f"Timezone override failed, continue without override: {e}")

        self.log.info("Chrome driver initialized successfully")

    def get_cookies(self, url: str = None):
        if not url:
            url = "https://weibo.com/newlogin?tabtype=weibo&gid=102803&openLoginLayer=0&url=https%3A%2F%2Fweibo.com%2F"
        self.driver.get(url)
        time.sleep(10)
        cookies = self.driver.get_cookies()
        self.log.info("cookies get")
        return cookies

    def check_cookies(self, username: str = "", check_url: str = ""):
        if self.cookies is None:
            self.log.error("cookies is None")
            return False
        try:
            session = requests.Session()
            for cookie in self.cookies:
                session.cookies.set(cookie["name"], cookie["value"])
            resp = session.get("https://weibo.com")
            html = resp.text
            if username in html:
                return True
            self.log.error("cookies invalid or username mismatch")
            return False
        except Exception:
            self.log.error("cookies invalid or username mismatch")
            return False

    def _login(self, url: str = "https://weibo.com", cookies: list = None, token: str = None):
        try:
            self.driver.set_page_load_timeout(45)
            self.driver.get(url=url)
            self.log.info("entered login page")
            time.sleep(5)
            if cookies:
                for cookie in cookies:
                    self.driver.add_cookie(cookie)
                self.log.info("cookies added")
                time.sleep(random.randint(10, 20))
                self.driver.get(url=url)
                self.log.info("cookies loaded")
                time.sleep(random.randint(5, 10))
            elif token:
                self.driver.add_cookie({
                    "name": "auth_token",
                    "value": token,
                    "domain": ".x.com"
                })
                time.sleep(5)
                self.driver.get(url=url)
                self.log.info("token loaded")
                time.sleep(2)
            return True
        except TimeoutException as e:
            try:
                self.driver.execute_script("window.stop();")
            except Exception:
                pass
            self.log.error(str(e))
            self.log.error("cookies load failed")
            return False
        except WebDriverException as e:
            self.log.error(str(e))
            self.log.error("cookies load failed")
            return False
        except Exception as e:
            self.log.error(str(e))
            self.log.error("cookies load failed")
            return False

    def close(self):
        self.driver.close()

    def quit(self):
        self.driver.quit()

    def get(self, url):
        self.driver.get(url)

    def find_xpath(self, XPATH: str = None):
        return self.driver.find_element(By.XPATH, XPATH)

    def find_xpaths(self, XPATH: str = None):
        return self.driver.find_elements(By.XPATH, XPATH)

    def send_content(self, XPATH: str = None, content: str = None):
        try:
            self.driver.find_element(By.XPATH, XPATH).send_keys(content)
            time.sleep(0.5)
        except Exception as e:
            self.log.error(str(e))

    def scroll(self, size: int = 200):
        self.driver.execute_script(f"window.scrollBy(0,{size})")
        time.sleep(0.5)

    def element_to_top(self, XPATH: str = None):
        element = self.driver.find_element(By.XPATH, XPATH)
        self.driver.execute_script("arguments[0].scrollIntoView();", element)
        time.sleep(0.5)

    def switch_to_frame(self, XPATH: str = None):
        frame = self.driver.find_element(By.XPATH, XPATH)
        self.driver.switch_to.frame(frame)
        time.sleep(0.5)

    def search_and_click(self, XPATH: str = "", waiting_time: float = 0.5, auto_scroll: bool = False):
        if not XPATH:
            self.log.error("XPATH is None")
            return
        try:
            if not auto_scroll:
                self.driver.find_element(By.XPATH, XPATH).click()
            else:
                times = 0
                while True:
                    try:
                        self.driver.find_element(By.XPATH, XPATH).click()
                        break
                    except Exception:
                        self.scroll()
                        times += 1
                        if times > 2:
                            self.log.error("Try too many times, click failed")
                            raise Exception("Try too many times, click failed")
            time.sleep(waiting_time)
            return
        except Exception:
            self.log.error("XPATH not found")
            raise Exception("XPATH not found")

    def search_only_bool(self, XPATH: str = "", auto_scroll: bool = False):
        try:
            if not auto_scroll:
                self.driver.find_element(By.XPATH, XPATH)
                return True
            for _ in range(2):
                try:
                    self.driver.find_element(By.XPATH, XPATH)
                    return True
                except Exception:
                    self.scroll()
            self.log.error("Try too many times, search failed")
            return False
        except NoSuchElementException:
            return False
        except Exception as e:
            self.log.error(str(e))
            return False

    def send_and_submit(self, xpath_content: str = "", xpath_button: str = "", content: str = ""):
        if not xpath_button or not xpath_content:
            self.log.error("xpath_button or xpath_content is None")
            return
        if not content:
            self.log.error("content is None")
            return
        try:
            self.driver.find_element(By.XPATH, xpath_content).send_keys(content)
            time.sleep(0.5)
            self.driver.find_element(By.XPATH, xpath_button).click()
            time.sleep(0.8)
        except Exception:
            self.log.error("button or content not found")
            raise Exception("button or content not found")

    def search_and_get_content(self, xpath: str = ""):
        if not xpath:
            self.log.error("xpath is None")
            return
        try:
            return self.driver.find_element(By.XPATH, xpath).text
        except Exception:
            self.log.error("xpath not found")
            raise Exception("xpath not found")

    def search_and_get_all_content(self, xpath: str = "", attribute=None) -> list[str]:
        if not xpath:
            self.log.error("xpath is None")
            return
        try:
            temp = self.driver.find_elements(By.XPATH, xpath)
            if not attribute:
                return [item.text for item in temp]
            return [{"text": item.text, attribute: item.get_attribute(attribute)} for item in temp]
        except Exception:
            self.log.error("xpath not found")
            return

    def go_back(self):
        self.driver.back()
        time.sleep(1)

    def open_new_tab(self, url: str = ""):
        self.driver.execute_script(f"window.open('{url}');")
        time.sleep(0.5)

    def click_image(self, parent_element, x_offset, y_offset):
        action_chains = ActionChains(self.driver)
        action_chains.move_to_element_with_offset(parent_element, x_offset, y_offset).click().perform()
        time.sleep(2)
        action_chains.reset_actions()
        time.sleep(1)

    def judge_bottom(self):
        js = "return document.documentElement.scrollTop + window.innerHeight >= document.documentElement.scrollHeight"
        return self.driver.execute_script(js)

    def swith_to_new_window(self, id):
        self.driver.switch_to.window(self.driver.window_handles[id])

    def switch_to_iframe(self, id):
        self.driver.switch_to.frame(id)
