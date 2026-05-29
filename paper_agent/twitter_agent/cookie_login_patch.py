import json
import json
import random
import time
from datetime import datetime
from http import HTTPStatus
from urllib.parse import urlparse

try:
    from twitter_agent.twitter_request import create_response
except ModuleNotFoundError:
    from twitter_request import create_response


def _normalize_profile_url(url: str):
    if not url:
        return None
    parsed = urlparse(url)
    path = (parsed.path or "").rstrip("/").lower()
    if not path:
        return None
    return f"x.com{path}"


def _profile_url_matches(actual_url: str, expected_url: str = None, account: str = None):
    actual_norm = _normalize_profile_url(actual_url)
    expected_norm = _normalize_profile_url(expected_url)
    if actual_norm and expected_norm and actual_norm == expected_norm:
        return True

    actual_tail = (actual_norm or "").split("/")[-1]
    expected_tail = (expected_norm or "").split("/")[-1]
    account_tail = (account or "").lstrip("@").rstrip("/").lower()
    return bool(actual_tail) and actual_tail in {expected_tail, account_tail}


def _extract_profile_href(bot):
    candidate_xpaths = [
        '//a[@aria-label="Profile"]',
        '//a[@data-testid="AppTabBar_Profile_Link"]',
        '//button[@data-testid="SideNav_AccountSwitcher_Button"]//a',
    ]
    for xpath in candidate_xpaths:
        try:
            elements = bot.driver.find_xpaths(XPATH=xpath)
        except Exception:
            elements = []
        for element in elements:
            try:
                href = element.get_attribute("href")
            except Exception:
                href = None
            if href and "x.com/" in href:
                return href
    return None


def _cookie_login_state(bot, expected_profile: str = None, account: str = None):
    profile_href = _extract_profile_href(bot)
    try:
        current_url = bot.driver.driver.current_url or ""
    except Exception:
        current_url = ""
    normalized_current = current_url.rstrip("/").lower()

    logged_in_markers = [
        '//button[@data-testid="SideNav_AccountSwitcher_Button"]',
        '//a[@data-testid="AppTabBar_Home_Link"]',
        '//a[@href="/compose/post"]',
        '//div[@data-testid="primaryColumn"]',
    ]
    has_logged_in_ui = any(bot.driver.find_xpaths(XPATH=xpath) for xpath in logged_in_markers)
    has_login_form = bool(bot.driver.find_xpaths(XPATH='//input[@name="text"]')) or bool(
        bot.driver.find_xpaths(XPATH='//a[contains(@href,"/i/flow/login")]')
    )

    if profile_href and _profile_url_matches(profile_href, expected_profile, account):
        return True, profile_href, current_url
    if not expected_profile and profile_href:
        return True, profile_href, current_url
    if has_logged_in_ui and not has_login_form and ("/home" in normalized_current or normalized_current in {"https://x.com", "https://twitter.com"}):
        return True, profile_href, current_url
    if expected_profile and not has_login_form and _profile_url_matches(current_url, expected_profile, account):
        return True, profile_href, current_url
    return False, profile_href, current_url


async def cookie_only_login_by_cookies(self, account_id: int, url: str = "https://twitter.com/?lang=zh"):
    create_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        search_sql = f"SELECT * FROM accounts_info WHERE accounts_info.Account_id = {account_id}"
        result = self.database.get_dict_data_sql(search_sql)[0]
        self.log.info("从数据库中获取到的账号信息:{}".format(result))
        cookies = result["Cookie"]
        token = result["Token"]
        ct0 = result["Ct0"]
        profile = result["URL"]
        account = result["Account"]
    except Exception as e:
        self.log.error("获取账号信息失败，原因:{}".format(e))
        return create_response(create_time=create_time, code=HTTPStatus.BAD_REQUEST, message="error", response=f"账号{account_id}cookies下线，利用cookies登录失败")

    try:
        if hasattr(self, "_ensure_live_driver"):
            await self._ensure_live_driver(force_reset=not self._driver_session_alive())
        if cookies:
            cookies = json.loads(cookies)
        elif token and ct0:
            cookies = [
                {"name": "auth_token", "path": "/", "value": token, "domain": ".x.com", "expiry": 1785316008, "secure": True, "httpOnly": True, "sameSite": "None"},
                {"name": "ct0", "path": "/", "value": ct0, "domain": ".x.com", "expiry": 1785316009, "secure": True, "httpOnly": False, "sameSite": "Lax"},
            ]
        else:
            sql = '''UPDATE accounts_info SET Cookie_Status = %s WHERE Account_id = %s;'''
            self.database.operation(sql, ("下线", account_id))
            self.log.error(f"账号{account_id}缺少可用的 cookie / auth_token / ct0，仅允许 cookie 登录")
            return create_response(create_time=create_time, code=HTTPStatus.BAD_REQUEST, message="error", response=f"账号{account_id}cookies下线，利用cookies登录失败")

        self.driver._login(url="https://x.com/home", cookies=cookies, token=None)

        success = False
        href = None
        current_url = ""
        probe_urls = [url for url in [profile, "https://x.com/home"] if url]
        for _ in range(6):
            time.sleep(random.uniform(4, 6))
            success, href, current_url = _cookie_login_state(self, expected_profile=profile, account=account)
            if success:
                break
            for probe_url in probe_urls:
                try:
                    self.driver.get(probe_url)
                except Exception:
                    pass
                time.sleep(random.uniform(2, 4))
                success, href, current_url = _cookie_login_state(self, expected_profile=profile, account=account)
                if success:
                    break
            if success:
                break

        if not success:
            self.log.error(f"账号{account_id} cookie 登录校验失败，profile={profile}, detected_profile={href}, current_url={current_url}")
            sql = '''UPDATE accounts_info SET Cookie_Status = %s WHERE Account_id = %s;'''
            self.database.operation(sql, ("下线", account_id))
            return create_response(create_time=create_time, code=HTTPStatus.BAD_REQUEST, message="error", response=f"账号{account_id}cookies下线，利用cookies登录失败")

        self.log.info(f"利用cookies登录成功，current_url={current_url}, profile_href={href}")
        refreshed_cookies = json.dumps(self.driver.get_cookies(url="https://x.com/home"))
        update_sql = '''UPDATE accounts_info SET Cookie = %s, Cookie_Status = %s, URL = %s, Latest_login_time = %s WHERE Account_id = %s;'''
        self.database.operation(update_sql, (refreshed_cookies, "在线", href or profile, datetime.now(), account_id))
        await self.get_user_profile(account_id=account_id)
        return create_response(create_time=create_time, code=HTTPStatus.OK, message="success", response=f"账号{account_id}cookies登录成功")
    except Exception as e:
        error_text = str(e)
        if "HTTPConnectionPool(host='localhost'" in error_text or "Max retries exceeded with url: /session/" in error_text:
            self.log.info(f"账号{account_id}的 webdriver 会话失活，重建驱动后重试 cookie 登录")
            if hasattr(self, "_ensure_live_driver"):
                try:
                    await self._ensure_live_driver(account_id=None, force_reset=True)
                    self.driver._login(url="https://x.com/home", cookies=cookies, token=None)
                    time.sleep(random.uniform(4, 6))
                    success, href, current_url = _cookie_login_state(self, expected_profile=profile, account=account)
                    if success:
                        self.log.info(f"利用cookies登录成功，current_url={current_url}, profile_href={href}")
                        refreshed_cookies = json.dumps(self.driver.get_cookies(url="https://x.com/home"))
                        update_sql = '''UPDATE accounts_info SET Cookie = %s, Cookie_Status = %s, URL = %s, Latest_login_time = %s WHERE Account_id = %s;'''
                        self.database.operation(update_sql, (refreshed_cookies, "在线", href or profile, datetime.now(), account_id))
                        await self.get_user_profile(account_id=account_id)
                        return create_response(create_time=create_time, code=HTTPStatus.OK, message="success", response=f"账号{account_id}cookies登录成功")
                except Exception as retry_error:
                    self.log.error(f"账号{account_id}cookie 登录重试失败，原因:{retry_error}")
        sql = '''UPDATE accounts_info SET Cookie_Status = %s WHERE Account_id = %s;'''
        self.database.operation(sql, ("下线", account_id))
        self.log.error(f"账号{account_id}cookies下线，利用cookies登录失败，原因:{e}")
        return create_response(create_time=create_time, code=HTTPStatus.BAD_REQUEST, message="error", response=f"账号{account_id}cookies下线，利用cookies登录失败")
