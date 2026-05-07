import os
import sys
pythonpath = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0,pythonpath)
import requests
import time
import requests
from requests.exceptions import RequestException
from .log import logger
import time
import string
import zipfile
from config import *
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from config import TIANQI_INFO,MAX_RETRIES


def get_valid_proxy(ip_api_url,log_path:str='./logs/ip/ip_log.log'):
    '''
    从天启获取IP，并验证IP的有效性，若有效，则返回host和port，若无效，则返回None
    -ip_api_url: 天启的IP api地址
    -log_path：请求ip的日志
    '''
    log = logger(log_path)  # 获取日志对象
    try:
        '''获取代理IP'''
        resp = requests.get(url=ip_api_url)
        resp.raise_for_status()  # 确保请求成功
        proxy_data = resp.json()["data"][0]
        proxy_host = proxy_data["ip"]
        proxy_port = proxy_data["port"]
        # ip_city = proxy_data["prov"]+'-'+ proxy_data["city"]
        log.info(f'获取到ip:{resp.text}')
    except RequestException as e:
        log.error(f"获取代理IP失败: {e}")
        return None
    try:
        proxy = {
            "http": f"http://{proxy_host}:{proxy_port}",
            "https": f"http://{proxy_host}:{proxy_port}"
        }
        time.sleep(2)
        # 测试代理是否可用
        response = requests.get("http://httpbin.org/ip", proxies=proxy, timeout=10)
        response_ip = response.json()["origin"]
        if response_ip==proxy_host:
            log.info(f"代理IP可用: {response.json()}")
            return {"ip":proxy_host,"port":proxy_port}
        else:
            log.info(f'代理IP无效')
            return None
    except RequestException as e:
        log.error(f"代理IP无效: {e}")
        return None
    
def get_ip_port(ip,time_long=3):  # ip是城市
    '''后处理天启API url，并请求ip'''
    # 获取城市的代码
    
    ip = CITY_INFO[ip]
    print('当前ip:',ip)
    parsed_url = urlparse(TIANQI_INFO["IP_API_URL"])
    query_params = parse_qs(parsed_url.query)
    query_params['type'] = ['json']
    query_params['time'] = [time_long]
    query_params['region'] = [ip]
    query_params['num'] = ['1']
    new_query = urlencode(query_params, doseq=True)
    # 完整的API地址
    new_url = parsed_url._replace(query=new_query)
    ip_api_url = urlunparse(new_url)
    retry_num = 0
    while retry_num < MAX_RETRIES:
        try:
            ip_port= get_valid_proxy(ip_api_url = ip_api_url)
            if ip_port:
                return ip_port
            if not ip_port:
                time.sleep(5)
                retry_num += 1
                continue
        except Exception as e:
            print(f'账号请求IP时发生错误：{e}')
    if retry_num == MAX_RETRIES:
        print(f'{MAX_RETRIES}次请求IP地址均失败')
        return None 
    
#  http://api.tianqiip.com/getip?secret=k8994m8h9rzggcsm&num=10&type=json&region=510000&port=1&time=3&ts=1&ys=1&cs=1&mr=1&sign=f4285d0b6c24fdd9fc01a272d2c38f20
#  http://api.tianqiip.com/getip?secret=k8994m8h9rzggcsm&num=1&type=json&port=1&time=3&ts=1&ys=1&cs=1&mr=1&sign=f4285d0b6c24fdd9fc01a272d2c38f20&region=110100
 
        
def create_proxyauth_extension(proxy_host, proxy_port,proxy_username, proxy_password,scheme='http', plugin_path=None):
    """Proxy Auth Extension
    args:
        proxy_host (str): domain or ip address, ie proxy.domain.com
        proxy_port (int): port
        proxy_username (str): auth username
        proxy_password (str): auth password
    kwargs:
        scheme (str): proxy scheme, default http
        plugin_path (str): absolute path of the extension
    return str -> plugin_path
    """
    if plugin_path is None:
        plugin_path = 'Selenium-Chrome-HTTP-Private-Proxy.zip'
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
        },
        "minimum_chrome_version":"22.0.0"
    }
    """
    background_js = string.Template(
        """
        var config = {
                mode: "fixed_servers",
                rules: {
                  singleProxy: {
                    scheme: "${scheme}",
                    host: "${host}",
                    port: parseInt(${port})
                  },
                  bypassList: ["foobar.com"]
                }
              };
        chrome.proxy.settings.set({value: config, scope: "regular"}, function() {});
        function callbackFn(details) {
            return {
                authCredentials: {
                    username: "${username}",
                    password: "${password}"
                }
            };
        }
        chrome.webRequest.onAuthRequired.addListener(
                    callbackFn,
                    {urls: ["<all_urls>"]},
                    ['blocking']
        );
        """
    ).substitute(
        host=proxy_host,
        port=proxy_port,
        username=proxy_username,
        password=proxy_password,
        scheme=scheme,
    )
    with zipfile.ZipFile(plugin_path, 'w') as zp:
        zp.writestr("manifest.json", manifest_json)
        zp.writestr("background.js", background_js)

    return plugin_path


# 天启IP 余额套餐支持的城市
CITY_INFO = {
    "上海市-上海市": "310100",
    "内蒙古自治区-兴安盟": "152200",
    "北京市-北京市": "110100",
    "四川省-泸州市": "510500",
    "四川省-成都市": "510100",
    "四川省-自贡市": "510300",
    "四川省-广元市": "510800",
    "安徽省-合肥市": "340100",
    "安徽省-淮南市": "340400",
    "安徽省-淮北市": "340600",
    "安徽省-蚌埠市": "340300",
    "安徽省-芜湖市": "340200",
    "安徽省-池州市": "341700",
    "安徽省-黄山市": "341000",
    "山东省-淄博市": "370300",
    "山东省-威海市": "371000",
    "山东省-烟台市": "370600",
    "山东省-日照市": "371100",
    "山东省-济南市": "370100",
    "广东省-珠海市": "440400",
    "广东省-广州市": "440100",
    "广东省-汕头市": "440500",
    "广东省-揭阳市": "445200",
    "广西省-桂林市": "450300",
    "江苏省-徐州市": "320300",
    "江苏省-苏州市": "320500",
    "江苏省-南京市": "320100",
    "江苏省-无锡市": "320200",
    "江苏省-宿迁市": "321300",
    "江苏省-南通市": "320600",
    "江苏省-淮安市": "320800",
    "江苏省-泰州市": "321200",
    "江苏省-镇江市": "321100",
    "江苏省-连云港市": "320700",
    "江苏省-扬州市": "321000",
    "江苏省-盐城市": "320900",
    "江西省-宜春市": "360900",
    "江西省-抚州市": "361000",
    "江西省-南昌市": "360100",
    "江西省-鹰潭市": "360600",
    "河北省-廊坊市": "131000",
    "河北省-石家庄市": "130100",
    "河北省-唐山市": "130200",
    "河北省-承德市": "130800",
    "河北省-秦皇岛市": "130300",
    "河北省-张家口市": "130700",
    "河南省-许昌市": "411000",
    "河南省-开封市": "410200",
    "河南省-三门峡市": "411200",
    "河南省-平顶山市": "410400",
    "浙江省-舟山市": "330900",
    "浙江省-杭州市": "330100",
    "浙江省-宁波市": "330200",
    "浙江省-衢州市": "330800",
    "浙江省-绍兴市": "330600",
    "浙江省-丽水市": "331100",
    "浙江省-嘉兴市": "330400",
    "浙江省-台州市": "331000",
    "浙江省-温州市": "330300",
    "浙江省-金华市": "330700",
    "浙江省-湖州市": "330500",
    "海南省-三亚市": "460200",
    "湖北省-黄冈市": "421100",
    "湖北省-襄阳市": "420600",
    "湖北省-荆门市": "420800",
    "湖北省-随州市": "421300",
    "湖北省-黄石市": "420200",
    "湖北省-咸宁市": "421200",
    "湖南省-郴州市": "431000",
    "湖南省-邵阳市": "430500",
    "湖南省-益阳市": "430900",
    "湖南省-湘西土家族苗族自治州": "433100",
    "湖南省-湘潭市": "430300",
    "福建省-南平市": "350700",
    "福建省-莆田市": "350300",
    "福建省-福州市": "350100",
    "福建省-三明市": "350400",
    "福建省-宁德市": "350900",
    "福建省-漳州市": "350600",
    "福建省-厦门市": "350200",
    "福建省-泉州市": "350500",
    "辽宁省-葫芦岛市": "211400",
    "辽宁省-辽阳市": "211000",
    "辽宁省-抚顺市": "210400",
    "辽宁省-营口市": "210800",
    "辽宁省-鞍山市": "210300",
    "辽宁省-锦州市": "210700",
    "辽宁省-大连市": "210200",
    "重庆市-重庆市": "500100",
    "陕西省-汉中市": "610700",
    "陕西省-咸阳市": "610400",
    "陕西省-商洛市": "611000",
    "陕西省-榆林市": "610800",
    "陕西省-安康市": "610900",
    "陕西省-西安市": "610100",
    "陕西省-渭南市": "610500",
    "陕西省-宝鸡市": "610300",
    "青海省-黄南藏族自治州": "632300"
}
