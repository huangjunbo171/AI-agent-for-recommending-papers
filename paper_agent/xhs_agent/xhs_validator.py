import os
import sys
pythonpath = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0,pythonpath)


from fastapi import HTTPException
from xhs_agent.xhs_request import *


def validata_base_fields(request):
    if request.ip:
        missing_fields = [field for field in ["ip_username", "ip_password"] if not getattr(request, field, None)]
        if missing_fields:
            raise HTTPException(status_code=400, detail=f"提供了 ip，则必须提供: {', '.join(missing_fields)}")
    return request

def validata_common_fields(request):
    if not request.account_id:
        raise HTTPException(status_code=400, detail="必须提供 `account_id`")   
    if not request.url:
        raise HTTPException(status_code=400, detail="必须提供 `url`")


def validate_request(request: InteractionRequest,path:str):
    """校验登录请求是否符合要求"""
    # 如果提供了 ip，则必须提供 ip_username 和 ip_password
    validata_base_fields(request)
    if path == '/login':
        if not request.phone and not request.account_id:
            raise HTTPException(status_code=400, detail="`phone` 和 `account_id` 至少提供一个")

        if (request.email_account and not request.email_password) or (request.email_password and not request.email_account):
            raise HTTPException(status_code=400, detail="`email_account` 和 `email_password` 需要一起提供")
    elif path == "/post":
        if not request.account_id:
            raise HTTPException(status_code=400, detail="必须提供 `account_id`")
        if not request.content:
            raise HTTPException(status_code=400, detail="必须提供要发布的内容 `content`")
        if not request.file_paths:
            raise HTTPException(status_code=400, detail="必须提供图片路径列表`file_paths`, 至少包含一张图片")
        if len(request.file_paths) == 1:
            video_extensions = ['.mp4', '.mov', '.avi', '.mkv']  # 视频格式
            file_extension = request.file_paths[0].split('.')[-1].lower()
            if file_extension in video_extensions and request.usage=='picture':
                raise HTTPException(status_code=400, detail="发布视频是，必须修改`usage`为video")
        if len(request.file_paths) == 1:
            image_extensions = ['.png', '.jpg', '.jpeg']  # 图片格式
            file_extension = request.file_paths[0].split('.')[-1].lower()
            if file_extension in image_extensions and request.usage=='video':
                raise HTTPException(status_code=400, detail="发布视频是，必须修改`usage`为picture")
            
                
    elif path=='/like' or path == '/follow' or path == '/notfollow' or path == '/collect':
        validata_common_fields(request)
    elif path == '/comment':
        validata_common_fields(request)
        if not request.content:
            raise HTTPException(status_code=400,detail="必须提供评论内容`content`")
    # elif path == '/complaint':
    #     validata_common_fields(request)
    #     # 哪些投诉原因必须得有二级/
    #     if not request.complaint_class1:
    #         raise HTTPException(status_code=400, detail="必须提供一级投诉类别 `complaint_class1`")
    #     if request.complaint_class1 in ["政治敏感","违反公德秩序","涉未成年不当内容","危害人身安全"] and not request.complaint_class2:
    #         raise HTTPException(status_code=400, detail="必须提供二级投诉类别 `complaint_class2`")
    #     if request.complaint_class1 in ["虚假、不实内容","不属于以上类型"] and (not request.complaint_class2 or not request.complaint_reason):
    #         raise HTTPException(status_code=400, detail="必须提供二级投诉类别 `complaint_class2`和原因`complaint_reason`")
    
    elif path == '/scrap' or path == '/getprofile' or path == "/history" or path == "/interaction" or path == "/personstyle" or path == '/interest':
        if not request.account_id:
            raise HTTPException(status_code=400, detail="必须提供 `account_id`")
    elif path == '/update_interest':
        if not request.account_id:
            raise HTTPException(status_code=400, detail="必须提供 `account_id`")
        if not request.interest:
            raise HTTPException(status_code=400, detail="必须提供 `interest`")
    return request
        
        

