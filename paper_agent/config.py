import os
import sys
pythonpath = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0,pythonpath)


DEFAULT_DRIVER_PATH =  r"D:\code\chromedriver-win64\chromedriver.exe"   # driver 路径 ，一般无需更改

KEY_WORDS_PATH = "./checklist_files/baijiahao_keywords.txt"  # 关键字路径，用来筛选文章 ，一般无需更改

# deepseek相关参数
DEEPSEEK_INFO = {
    "API_KEY": "sk-85cb779a99424686a635adac50befc9b", # DeepSeek的 API Key，可在 https://api-docs.deepseek.com/ 申请
    "MODEL": 'deepseek-reasoner' ,      # DeepSeek模型，指定使用 R1 模型（deepseek-reasoner）或者 V3 模型（deepseek-chat），一般无需更改
    "TEMPERATURE":1.0,                  # 采样温度，介于 0 和 2 之间，默认是1.0，一般无需更改
    "TOP_P": 1 ,                        # 模型会考虑前 top_p 概率的 token 的结果，默认是 1，一般无需更改
    "MAX_TOKEN": 8192 ,                 # 默认是4096，介于 1 到 8192 间的整数，限制一次请求中模型生成 completion 的最大 token 数，一般无需更改
    "PRESENCE_PENALTY": 0               # 惩罚因子，介于-2.0到2.0之间的数字，默认是0，一般无需更改
}



# 天启IP的信息，
TIANQI_INFO = {
    # 可从 https://www.tianqiip.com/getIp 获取
    "IP_API_URL": "http://api.tianqiip.com/getip?secret=k8994m8h9rzggcsm&num=10&type=json&region=510000&port=1&time=3&ts=1&ys=1&cs=1&mr=1&sign=f4285d0b6c24fdd9fc01a272d2c38f20",
    "USERNAME": "liununew",   # 账号名
    "PASSWORD": "liudan123ewq" # 密码
}



# 数据库相关参数
DATABASE_INFO = {
    "HOST": '172.16.32.11',		# 主机名（或IP地址），如果是本地则改为localhost
    "PORT": 30104,				# 端口号，默认为3306
    "USER": 'root',			    # 用户名，默认是root
    "PASSWORD": '123ewq'	    # 密码，修改为自己的密码
}


# 得塔云相关参数
DETAYUN_INFO = {
    'KEY': 'kUs67wtk8hPOxpw4NkgU',  # 在https://www.detayun.cn/openapi处申请key     
    'VERIFY_ID': '44'   # 验证码类型,百家号旋转图像id为44，一般无需更改
}    
     
MAX_RETRIES = 5  # 请求deepseek的最大次数，若请求失败，可重复请求/请求IP的最大次数，一般无需更改

MIMN_IP = {
    'IP':'127.0.0.1',
    'PORT':'7890'
}
# from zoneinfo import ZoneInfo
# datetime.now(ZoneInfo("Asia/Shanghai")) 