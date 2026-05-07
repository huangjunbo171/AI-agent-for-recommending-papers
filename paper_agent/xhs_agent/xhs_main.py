import os
import sys
pythonpath = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0,pythonpath)
import shutil
from datetime import datetime
from fastapi import FastAPI, Depends,Request,UploadFile, File
import uvicorn
from typing import List
from xhs_agent.xhs_request import InteractionRequest,create_response
from xhs_agent.xhs_bot import XiaohongshuBot
from xhs_agent.xhs_validator import validate_request
import time
from http import HTTPStatus

app = FastAPI()


def get_bot(raw_request: InteractionRequest,request:Request):
    path = request.url.path  # 获取当前请求路径
    validate_request(raw_request,path)
    return XiaohongshuBot(raw_request.log_path, raw_request.ip, raw_request.ip_username, raw_request.ip_password)


@app.post("/login")
async def create_chat_completion(raw_request: InteractionRequest,bot=Depends(get_bot)):
    # bot = XiaohongshuBot(raw_request.log_path,raw_request.ip,raw_request.ip_username,raw_request.ip_password)
    response = await bot.login_by_cookies(int(raw_request.account_id))
    bot.driver.quit()
    time.sleep(2)
    return response

@app.post("/post")
async def create_chat_completion(raw_request: InteractionRequest,bot=Depends(get_bot)):
    # bot = XiaohongshuBot(raw_request.log_path,raw_request.ip,raw_request.ip_username,raw_request.ip_password)
    response = await bot.posts(int(raw_request.account_id),raw_request.file_paths,raw_request.title,raw_request.content,raw_request.tags,raw_request.usage)
    bot.driver.quit()
    time.sleep(2)
    return response

@app.post("/like")
async def create_chat_completion(raw_request: InteractionRequest,bot=Depends(get_bot)):
    # bot = XiaohongshuBot(raw_request.log_path,raw_request.ip,raw_request.ip_username,raw_request.ip_password)
    response = await bot.likes(int(raw_request.account_id),raw_request.url)
    bot.driver.quit()
    time.sleep(2)
    return response

@app.post("/comment")
async def create_chat_completion(raw_request: InteractionRequest,bot=Depends(get_bot)):
    # bot = XiaohongshuBot(raw_request.log_path,raw_request.ip,raw_request.ip_username,raw_request.ip_password)
    response = await bot.comments(int(raw_request.account_id),raw_request.url,raw_request.content)
    bot.driver.quit()
    time.sleep(2)
    return response

@app.post("/follow")
async def create_chat_completion(raw_request: InteractionRequest,bot=Depends(get_bot)):
    # bot = XiaohongshuBot(raw_request.log_path,raw_request.ip,raw_request.ip_username,raw_request.ip_password)
    response = await bot.follows(int(raw_request.account_id),raw_request.url)
    bot.driver.quit()
    time.sleep(2)
    return response

@app.post("/notfollow")
async def create_chat_completion(raw_request: InteractionRequest,bot=Depends(get_bot)):
    # bot = XiaohongshuBot(raw_request.log_path,raw_request.ip,raw_request.ip_username,raw_request.ip_password)
    response = await bot.notfollows(int(raw_request.account_id),raw_request.url)
    bot.driver.quit()
    time.sleep(2)
    return response

@app.post("/collect")
async def create_chat_completion(raw_request: InteractionRequest,bot=Depends(get_bot)):
    # bot = XiaohongshuBot(raw_request.log_path,raw_request.ip,raw_request.ip_username,raw_request.ip_password)
    response = await bot.collects(int(raw_request.account_id),raw_request.url)
    bot.driver.quit()
    time.sleep(2)
    return response

@app.post("/getprofile")
async def create_chat_completion(raw_request: InteractionRequest,bot=Depends(get_bot)):
    # bot = XiaohongshuBot(raw_request.log_path,raw_request.ip,raw_request.ip_username,raw_request.ip_password)
    response = await bot.get_user_profile(int(raw_request.account_id))
    bot.driver.quit()
    time.sleep(2)
    return response

@app.post("/scrap")
async def create_chat_completion(raw_request: InteractionRequest,bot=Depends(get_bot)):
    # bot = XiaohongshuBot(raw_request.log_path,raw_request.ip,raw_request.ip_username,raw_request.ip_password)
    response = await bot.scrap_content(int(raw_request.account_id),raw_request.num)
    bot.driver.quit()
    time.sleep(2)
    return response

@app.post("/personstyle")
async def create_chat_completion(raw_request: InteractionRequest,bot=Depends(get_bot)):
    # bot = XiaohongshuBot(raw_request.log_path,raw_request.ip,raw_request.ip_username,raw_request.ip_password)
    response = await bot.get_account_character(int(raw_request.account_id))
    bot.driver.quit()
    time.sleep(2)
    return response

@app.post("/interaction") # 获取历史交互
async def create_chat_completion(raw_request: InteractionRequest,bot=Depends(get_bot)):
    # bot = XiaohongshuBot(raw_request.log_path,raw_request.ip,raw_request.ip_username,raw_request.ip_password)
    response = await bot.get_account_interaction(int(raw_request.account_id))
    bot.driver.quit()
    time.sleep(2)
    return response

@app.post("/history")
async def create_chat_completion(raw_request: InteractionRequest,bot=Depends(get_bot)):
    # bot = XiaohongshuBot(raw_request.log_path,raw_request.ip,raw_request.ip_username,raw_request.ip_password)
    response = await bot.get_account_history(int(raw_request.account_id))
    bot.driver.quit()
    time.sleep(2)
    return response


@app.post("/interest")  # 获取历史兴趣
async def create_chat_completion(raw_request: InteractionRequest,bot=Depends(get_bot)):
    # bot = XiaohongshuBot(raw_request.log_path,raw_request.ip,raw_request.ip_username,raw_request.ip_password)
    response = await bot.get_history_interests(int(raw_request.account_id))
    bot.driver.quit()
    time.sleep(2)
    return response

@app.post("/update_interest")  # 更新兴趣
async def create_chat_completion(raw_request: InteractionRequest,bot=Depends(get_bot)):
    # bot = XiaohongshuBot(raw_request.log_path,raw_request.ip,raw_request.ip_username,raw_request.ip_password)
    response = await bot.update_account_interest(int(raw_request.account_id),raw_request.interest)
    bot.driver.quit()
    time.sleep(2)
    return response



@app.post("/upload")
async def upload_fileupload_file(files: List[UploadFile] = File(...)):
    # 定义上传和下载的文件目录
    try:
        create_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        current_date = datetime.now().strftime("%Y-%m-%d")  # 获取当前日期
        UPLOAD_DIR = f"./information/xhs/{current_date}"
        # 如果目录不存在则创建
        if not os.path.exists(UPLOAD_DIR):
            os.makedirs(UPLOAD_DIR)
        saved_paths = []
        for file in files:
            # 保存文件到服务器上传目录
            file_location = os.path.join(UPLOAD_DIR, file.filename)
            if not os.path.exists(file_location):
                with open(file_location, "wb") as buffer:
                    shutil.copyfileobj(file.file, buffer)
                saved_paths.append(file_location)
            # else:
            #     return {"filename":file_location,"status":"文件名已经存在！"}
        return create_response(create_time=create_time,code=HTTPStatus.OK,message='success',response=saved_paths)
        # return {"saved_paths":saved_paths,"status":"图像/视频上传成功！"}
    except:
        return create_response(create_time=create_time,code=HTTPStatus.BAD_REQUEST,message='error',response="图像/视频上传失败")



# 主程序入口，用于启动Uvicorn服务器
if __name__ == "__main__":
    uvicorn.run(
        app=app,
        host="127.0.0.1",  # 设置监听地址
        port=30103,  # 设置监听端口
        log_level="debug",  # 设置日志级别
        workers=1,  # 设置工作进程数量
    )
    

    