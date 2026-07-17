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


def _has_logged_in_ui(bot):
    strict_logged_in_markers = [
        '//button[@data-testid="SideNav_AccountSwitcher_Button"]',
        '//a[@data-testid="SideNav_NewTweet_Button"]',
        '//button[@data-testid="SideNav_NewTweet_Button"]',
        '//a[@href="/compose/post"]',
        '//a[@data-testid="AppTabBar_Profile_Link"]',
    ]
    for xpath in strict_logged_in_markers:
        try:
            if bot.driver.find_xpaths(XPATH=xpath):
                return True
        except Exception:
            continue
    return False


def _cookie_login_state(bot, expected_profile: str = None, account: str = None):
    profile_href = _extract_profile_href(bot)
    try:
        current_url = bot.driver.driver.current_url or ""
    except Exception:
        current_url = ""
    parsed_current = urlparse(current_url)
    normalized_current = current_url.rstrip("/").lower()
    current_host = (parsed_current.netloc or "").lower().removeprefix("www.")
    current_path = (parsed_current.path or "").lower()

    has_logged_in_ui = _has_logged_in_ui(bot)
    login_form_markers = [
        '//input[@name="text" and @autocomplete="username"]',
        '//input[@name="password"]',
        '//button[@data-testid="LoginForm_Login_Button"]',
        '//button[@data-testid="ocfEnterTextNextButton"]',
        '//a[contains(@href,"/i/flow/login")]',
    ]
    has_login_form = any(bot.driver.find_xpaths(XPATH=xpath) for xpath in login_form_markers)
    in_login_flow = "/i/flow/login" in current_path
    on_x_domain = current_host in {"x.com", "twitter.com"}

    if has_logged_in_ui and not has_login_form and not in_login_flow:
        return True, profile_href, current_url
    if on_x_domain and "/compose/post" in normalized_current and not has_login_form:
        return True, profile_href, current_url
    if has_logged_in_ui and profile_href and _profile_url_matches(profile_href, expected_profile, account):
        return True, profile_href, current_url
    return False, profile_href, current_url


def _build_token_ct0_cookies(token: str, ct0: str):
    if not token or not ct0:
        return []
    return [
        {
            "name": "auth_token",
            "path": "/",
            "value": token,
            "domain": ".x.com",
            "expiry": 1785316008,
            "secure": True,
            "httpOnly": True,
            "sameSite": "None",
        },
        {
            "name": "ct0",
            "path": "/",
            "value": ct0,
            "domain": ".x.com",
            "expiry": 1785316009,
            "secure": True,
            "httpOnly": False,
            "sameSite": "Lax",
        },
    ]


def _contains_auth_cookies(cookies):
    cookie_names = {str(item.get("name", "")).strip() for item in cookies if isinstance(item, dict)}
    return "auth_token" in cookie_names and "ct0" in cookie_names


async def _refresh_profile_after_cookie_login(bot, account_id: int):
    try:
        await bot.get_user_profile(account_id=account_id)
    except Exception as profile_error:
        bot.log.error(f"账号{account_id}cookie登录已经成功，但刷新用户资料失败，原因:{profile_error}")


async def cookie_only_login_by_cookies(self, account_id: int, url: str = "https://twitter.com/?lang=zh"):
    create_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    login_verified = False
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
        if hasattr(self, "_prepare_account_driver"):
            self._prepare_account_driver(account_id)
        if hasattr(self, "_ensure_live_driver"):
            await self._ensure_live_driver(force_reset=not self._driver_session_alive())
        db_cookies = json.loads(cookies) if cookies else []
        token_ct0_cookies = _build_token_ct0_cookies(token, ct0)
        login_candidates = []
        if db_cookies:
            login_candidates.append(("cookie", db_cookies))
            if token_ct0_cookies and not _contains_auth_cookies(db_cookies):
                self.log.info(f"账号{account_id}的 Cookie 中缺少 auth_token/ct0，回退准备使用 Token + Ct0 登录")
                login_candidates.append(("token_ct0", token_ct0_cookies))
        elif token_ct0_cookies:
            login_candidates.append(("token_ct0", token_ct0_cookies))
        else:
            sql = '''UPDATE accounts_info SET Cookie_Status = %s WHERE Account_id = %s;'''
            self.database.operation(sql, ("下线", account_id))
            self.log.error(f"账号{account_id}缺少可用的 cookie / auth_token / ct0，仅允许 cookie 登录")
            return create_response(create_time=create_time, code=HTTPStatus.BAD_REQUEST, message="error", response=f"账号{account_id}cookies下线，利用cookies登录失败")

        success = False
        href = None
        current_url = ""
        probe_urls = [url for url in [profile, "https://x.com/home", "https://x.com/compose/post"] if url]
        login_method = None
        last_candidate_name = None
        last_candidate_cookies = None

        for candidate_name, candidate_cookies in login_candidates:
            last_candidate_name = candidate_name
            last_candidate_cookies = candidate_cookies
            if candidate_name == "token_ct0" and hasattr(self, "_ensure_live_driver"):
                await self._ensure_live_driver(account_id=None, force_reset=True)
            try:
                login_started = self.driver._login(url="https://x.com/home", cookies=candidate_cookies, token=None)
                if login_started is False:
                    self.log.error(f"账号{account_id}使用{candidate_name}注入登录失败，原因: driver login returned false")
                    continue
            except Exception as candidate_error:
                self.log.error(f"账号{account_id}使用{candidate_name}注入登录失败，原因:{candidate_error}")
                continue

            for _ in range(6):
                time.sleep(random.uniform(4, 6))
                success, href, current_url = _cookie_login_state(self, expected_profile=profile, account=account)
                if success:
                    login_method = candidate_name
                    break
                for probe_url in probe_urls:
                    try:
                        self.driver.get(probe_url)
                    except Exception:
                        pass
                    time.sleep(random.uniform(2, 4))
                    success, href, current_url = _cookie_login_state(self, expected_profile=profile, account=account)
                    if success:
                        login_method = candidate_name
                        break
                if success:
                    break
            if success:
                break

        if not success:
            if token_ct0_cookies and "token_ct0" not in [name for name, _ in login_candidates]:
                self.log.info(f"账号{account_id}准备追加使用 Token + Ct0 进行登录兜底")
            self.log.error(f"账号{account_id} cookie 登录校验失败，profile={profile}, detected_profile={href}, current_url={current_url}")
            sql = '''UPDATE accounts_info SET Cookie_Status = %s WHERE Account_id = %s;'''
            self.database.operation(sql, ("下线", account_id))
            return create_response(create_time=create_time, code=HTTPStatus.BAD_REQUEST, message="error", response=f"账号{account_id}cookies下线，利用cookies登录失败")

        self.log.info(f"利用{login_method or 'cookies'}登录成功，current_url={current_url}, profile_href={href}")
        refreshed_cookies = json.dumps(self.driver.get_cookies(url="https://x.com/home"))
        update_sql = '''UPDATE accounts_info SET Cookie = %s, Cookie_Status = %s, URL = %s, Latest_login_time = %s WHERE Account_id = %s;'''
        self.database.operation(update_sql, (refreshed_cookies, "在线", href or profile, datetime.now(), account_id))
        login_verified = True
        await _refresh_profile_after_cookie_login(self, account_id=account_id)
        return create_response(create_time=create_time, code=HTTPStatus.OK, message="success", response=f"账号{account_id}cookies登录成功")
    except Exception as e:
        error_text = str(e)
        if "HTTPConnectionPool(host='localhost'" in error_text or "Max retries exceeded with url: /session/" in error_text:
            self.log.info(f"账号{account_id}的 webdriver 会话失活，重建驱动后重试 cookie 登录")
            if hasattr(self, "_ensure_live_driver"):
                try:
                    await self._ensure_live_driver(account_id=None, force_reset=True)
                    retry_cookies = last_candidate_cookies
                    if retry_cookies is None:
                        retry_cookies = json.loads(cookies) if cookies else _build_token_ct0_cookies(token, ct0)
                    login_started = self.driver._login(url="https://x.com/home", cookies=retry_cookies, token=None)
                    if login_started is False:
                        raise RuntimeError(f"driver login returned false during retry for {last_candidate_name or 'unknown'}")
                    time.sleep(random.uniform(4, 6))
                    success, href, current_url = _cookie_login_state(self, expected_profile=profile, account=account)
                    if success:
                        self.log.info(f"利用{last_candidate_name or 'cookies'}登录成功，current_url={current_url}, profile_href={href}")
                        refreshed_cookies = json.dumps(self.driver.get_cookies(url="https://x.com/home"))
                        update_sql = '''UPDATE accounts_info SET Cookie = %s, Cookie_Status = %s, URL = %s, Latest_login_time = %s WHERE Account_id = %s;'''
                        self.database.operation(update_sql, (refreshed_cookies, "在线", href or profile, datetime.now(), account_id))
                        login_verified = True
                        await _refresh_profile_after_cookie_login(self, account_id=account_id)
                        return create_response(create_time=create_time, code=HTTPStatus.OK, message="success", response=f"账号{account_id}cookies登录成功")
                except Exception as retry_error:
                    self.log.error(f"账号{account_id}cookie 登录重试失败，原因:{retry_error}")
        if login_verified:
            self.log.error(f"账号{account_id}cookie登录已经验证成功，但后续流程出错，不将cookie标记为下线，原因:{e}")
            return create_response(create_time=create_time, code=HTTPStatus.OK, message="success", response=f"账号{account_id}cookies登录成功")
        sql = '''UPDATE accounts_info SET Cookie_Status = %s WHERE Account_id = %s;'''
        self.database.operation(sql, ("下线", account_id))
        self.log.error(f"账号{account_id}cookies下线，利用cookies登录失败，原因:{e}")
        return create_response(create_time=create_time, code=HTTPStatus.BAD_REQUEST, message="error", response=f"账号{account_id}cookies下线，利用cookies登录失败")
