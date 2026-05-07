import time
from typing import Dict, List, Literal, Optional, Union
from pydantic import BaseModel, Field
from http import HTTPStatus
from fastapi.responses import JSONResponse
from datetime import datetime

# 登录请求参数
class InteractionRequest(BaseModel):
    log_path: Optional[str] = "./logs/xhs/xhs_log.log"  # log文件路径     
    ip: Optional[Union[str, int]] = None       # ip 区号   
    ip_username: Optional[str] = None           # 天启账号
    ip_password: Optional[str] = None           # 天启密码
    phone: Optional[str] = None         # 手机号
    email_account: Optional[str] = '13205412656' # 邮箱账号
    email_password: Optional[str] = '1q2w3e4r@' # 邮箱密码
    account_id: Optional[Union[str,int]] = None       # 账号id     

    # 发布
    content: Optional[str] = None                   # 要发布的内容
    usage: Optional[str] = 'picture'    # 发布图文还是视频，默认是picture，要发布视频时修改为video
    file_paths: Optional[List[str]] = None          # 图像路径，list
    title: Optional[str]= None       # 输入标题
    tags: Optional[Union[str,List[str]]] = None  # 话题标签  
        
    url: Optional[str] = None        # 要点赞/评论/收藏/关注/取消关注/的帖子链接或者作者主页链接  
    content: Optional[str] = None     # 要评论的内容   
    num: Optional[int] = 10  # 要爬取的内容数量，默认是爬取首页的10个
    interest: Optional[Union[str,List[str]]] = None # 要更新的兴趣



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