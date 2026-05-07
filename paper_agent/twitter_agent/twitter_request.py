import time
from typing import Dict, List, Literal, Optional, Union
from pydantic import BaseModel, Field
from http import HTTPStatus
from fastapi.responses import JSONResponse
from datetime import datetime

# 登录请求参数
class InteractionRequest(BaseModel):
    log_path: Optional[str] = "./logs/twitter/twitter_log.log"  # log文件路径     
    phone: Optional[str] = None         # 手机号
    email_account: Optional[str] = None # 邮箱账号
    email_password: Optional[str] = None # 邮箱密码
    account_id: Optional[Union[str,int]] = None       # 账号id   
    content: Optional[str] = None                   # 要发布的内容/评论的内容/转发的内容
    file_paths: Optional[List[str]] = None          # 要发布的图像/视频路径，list
    url: Optional[str] = None        # 要点赞/评论/转发/bookmark/关注/取消关注/要爬取的某网页
    num: Optional[int] = 10  # 要爬取的内容数量，默认是爬取首页的10个
    interest: Optional[Union[str,List[str]]] = None # 要更新的兴趣
    keyword: Optional[str] = None  # 关键字搜索，热搜词



class InteractionResponse(BaseModel):
    create_time:str
    code: str
    message: str
    response: Union[
        str,
        List[Dict[str, Optional[Union[int, str, List[str]]]]],  # Dict内的值是str或List[str]
        List[str],
        Dict[str, str]
    ]
    
def create_response(create_time:str,code:HTTPStatus,message:str,response):
    return JSONResponse(
        InteractionResponse(
            create_time=create_time,
            code=str(code.value),
            message=message,
            response=response
        ).model_dump(),  
        status_code=code.value
    )