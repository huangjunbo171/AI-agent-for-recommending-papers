# import openai
# openai.api_key ="EMPTY"
# openai.api_base = "http://127.0.0.1:8868/v1"   
from utils.utils import timer,split_think_and_answer
import re
import requests
import time
import os
import base64
import json
import httpx
import asyncio
@timer
async def content_generation(prompt):
    # response = openai.ChatCompletion.create(model='/data/yetong/tools/Qwen1.5-72B-Chat-GPTQ-Int4', messages=prompt, n=1, stop=["<|im_end|>", "<|endoftext|>", "<|im_start|>"])
    # response = response['choices'][0]['message']['content']
    url = "http://region-3.seetacloud.com:47826/general"
    prompt = {"messages":prompt}
    response = requests.post(url,json=prompt).json()
    return response["response"][0]




# qwen3-32B-idata，使用不思考模式
async def general_generation(prompt):
    '''idata,不使用思考模式'''
    data = {"model":"Qwen/Qwen3-32B","messages":prompt,"n":1,"stop":["&lt;|im_end|&gt;", "&lt;|endoftext|&gt;", "&lt;|im_start|&gt;"],"chat_template_kwargs": {"enable_thinking": False}}
    url = "https://www.chattydog.top/llm/chat" 
    # 最多尝试调用十次 
    max_retries = 10
    for attempt in range(max_retries):
        try:
            response = requests.post(url, json=data, timeout=60)
            response.raise_for_status()  # 检查 HTTP 状态码
            response_json = response.json()

            return response_json['choices'][0]['message']['content']

        except Exception as e:
            print(f"调用失败 (第 {attempt+1} 次): {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(3 * (attempt + 1))  # 逐次增加等待时间
            else:
                return  
            

# qwen3-32B,使用思考模式，返回think和answer
async def general_generation_think(prompt):
    '''idata,使用思考模式'''
    data = {"model":"Qwen/Qwen3-32B","messages":prompt,"n":1,"stop":["&lt;|im_end|&gt;", "&lt;|endoftext|&gt;", "&lt;|im_start|&gt;"],"chat_template_kwargs": {"enable_thinking": True}}
    url = "https://www.chattydog.top/llm/chat"   

    # 最多尝试调用十次 
    max_retries = 10
    for attempt in range(max_retries):
        try:
            response = requests.post(url, json=data, timeout=30)
            response.raise_for_status()  # 检查 HTTP 状态码
            response_json = response.json()

            response_text = response_json['choices'][0]['message']['content']
            think,answer = split_think_and_answer(response_text)
            if think == '' or answer == '':
                continue
            return think,answer

        except Exception as e:
            print(f"调用失败 (第 {attempt+1} 次): {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(3 * (attempt + 1))  # 逐次增加等待时间
            else:
                return None,None


# async def general_generation(prompt):
#     '''idata,不使用思考模式'''
#     data = {
#         "model":"Qwen/Qwen3-32B",
#         "messages":prompt,
#         "n":1,
#         "stop":["&lt;|im_end|&gt;", "&lt;|endoftext|&gt;", "&lt;|im_start|&gt;"],
#         "chat_template_kwargs": {"enable_thinking": False}
#     }
#     url = "http://www.chattydog.top/llm/chat"   

#     # 最多尝试调用十次 
#     max_retries = 10
#     async with httpx.AsyncClient(timeout=30) as client: 
#         for attempt in range(max_retries):
#             try:
#                 response = await client.post(url, json=data)  # 异步 POST
#                 response.raise_for_status()  # 检查 HTTP 状态码
#                 response_json = response.json()
#                 return response_json['choices'][0]['message']['content']

#             except  Exception as e:
#                 print(f"调用失败 (第 {attempt+1} 次): {e}")
#                 if attempt < max_retries - 1:
#                     await asyncio.sleep(3 * (attempt + 1))  
#                 else:
#                     return None




# 发帖
async def generation_post(text,model,language="中文简体",output_len=1000,character=None,style='formal'):
    data = {"input": text,
            "model": model,  
            "language":language,  
            "description":character,
            "output_len":output_len,
            "style":style}
    api = "http://172.16.32.11:30103/post"  #发帖
    start = time.time()
    response = requests.post(api, json=data).json()
    end = time.time()
    response_time = end - start
    return response,response_time    # 返回的是字符串




# 转发或者评论
async def generation_comment(text,model,language="中文简体",output_len=1000,character=None,style='formal'):
    data = {"input": text,
            "model": model,  
            "language":language,  
            "description":character,
            "style":style,
            "output_len":output_len}
    api = "http://172.16.32.11:30103/comment" #发帖
    start = time.time()
    response = requests.post(api, json=data).json()
    end = time.time()
    response_time = end - start
    return response,response_time




async def picture_generation(prompt):
    # 设置API密钥和请求URL
    ARK_API_KEY = "94abcc98-9ec1-4340-8217-5cf14264732f"
    url = "https://ark.cn-beijing.volces.com/api/v3/images/generations"

    # 设置请求头
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {ARK_API_KEY}"
    }

    # 设置请求体JSON数据
    data = {
        "model": "doubao-seedream-3-0-t2i-250415",
        "prompt": prompt,
        "response_format": "b64_json",
        "size": "1024x1024",
        "seed": 12,
        "guidance_scale": 2.5,
        "watermark": False
    }

    
    # 发送POST请求
    response = requests.post(url, headers=headers, data=json.dumps(data))
    
    # 检查响应状态码
    if response.status_code == 200:
        # 请求成功，打印响应内容
        images = response.json()['data']
    else:
        # 请求失败，打印错误信息
        print(f"请求失败，状态码: {response.status_code}, 错误信息: {response.text}")
        images = None
    if images:
        # 处理返回的图片数据
        
        current_time = time.strftime("%Y-%m-%d-%H-%M-%S", time.localtime())
        abs_path = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
        save_dir = os.path.join(abs_path,f"images\\{current_time}")
        if not os.path.exists(save_dir):
            os.makedirs(save_dir)
        image_paths = []
        for i, image in enumerate(images):
            # 将base64编码的图片数据解码并保存为文件
            image_data = base64.b64decode(image['b64_json'])
            save_path = os.path.join(save_dir, f"image_{i}.png")
            with open(save_path, "wb") as f:
                f.write(image_data)
            image_paths.append(save_path)
        # 返回图片路径
        return image_paths
    else:
        return []



if __name__ == '__main__':
    import asyncio
    # str1.encode('utf-8').decode('unicode_escape')
    async def main():
        # print(await general_generation([{'role':'system','content':'你好'}]))
        print(await generation_post(text='''support kamala harris''',model='Qwen-72b-Instruct',language='英文'))
    asyncio.run(main())