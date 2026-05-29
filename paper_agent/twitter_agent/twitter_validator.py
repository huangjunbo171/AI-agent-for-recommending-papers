import os
import sys
pythonpath = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0,pythonpath)


from fastapi import HTTPException
try:
    from twitter_agent.twitter_request import *
except ModuleNotFoundError:
    from twitter_request import *


# def validata_base_fields(request):
#     if request.ip:
#         missing_fields = [field for field in ["ip_username", "ip_password"] if not getattr(request, field, None)]
#         if missing_fields:
#             raise HTTPException(status_code=400, detail=f"提供了 ip，则必须提供: {', '.join(missing_fields)}")
#     return request

def validata_common_fields(request):
    if not request.account_id:
        raise HTTPException(status_code=400, detail="必须提供 `account_id`")   
    if not request.url:
        raise HTTPException(status_code=400, detail="必须提供 `url`")


def validate_request(request: InteractionRequest,path:str):
    """校验登录请求是否符合要求"""
    # 如果提供了 ip，则必须提供 ip_username 和 ip_password
    # validata_base_fields(request)
    if path == '/login':
        if not request.account_id:
            raise HTTPException(status_code=400, detail="必须提供`account_id`")
    elif path == "/post":
        if not request.account_id:
            raise HTTPException(status_code=400, detail="必须提供 `account_id`")
        if not request.content:
            raise HTTPException(status_code=400, detail="必须提供要发布的内容 `content`")
        
    elif path=='/like' or path == '/follow' or path == '/notfollow' or path == '/transmit' or path == '/bookmark':
        validata_common_fields(request)
    elif path == '/comment':
        validata_common_fields(request)
        if not request.content:
            raise HTTPException(status_code=400,detail="必须提供评论内容`content`")
   
    elif path == '/scrap' or path == '/getprofile' or path == "/history" or path == "/interaction" or path == "/personstyle" or path == 'hotwords' or path == '/interest':
        if not request.account_id:
            raise HTTPException(status_code=400, detail="必须提供 `account_id`")
    elif path == '/wordscrap':
        if not request.account_id:
            raise HTTPException(status_code=400, detail="必须提供 `account_id`")
        if not request.keyword:
            raise HTTPException(status_code=400, detail="必须提供 `account_id`")
    elif path == '/update_interest':
        if not request.account_id:
            raise HTTPException(status_code=400, detail="必须提供 `keyword`")
        if not request.interest:
            raise HTTPException(status_code=400, detail="必须提供 `interest`")
    return request
        
        

