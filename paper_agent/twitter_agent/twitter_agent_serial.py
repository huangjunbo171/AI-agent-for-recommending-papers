import os
import sys 
pythonpath = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0,pythonpath)
from utils.log import logger
from utils.sql import sql_dataset
try:
    from twitter_agent.twitter_bot import TwitterBot
    from twitter_agent.twitter_planner import TwitterPlanner
    from twitter_agent.cookie_login_patch import cookie_only_login_by_cookies
    from paper_agent.paper_agent.paper_agent import PaperAgent
    from paper_agent.scrap_objects import ScrapObjects
except ModuleNotFoundError:
    from twitter_bot import TwitterBot
    from twitter_planner import TwitterPlanner
    from cookie_login_patch import cookie_only_login_by_cookies
    from paper_agent.paper_agent import PaperAgent
    from paper_agent.scrap_objects import ScrapObjects
from datetime import datetime,timedelta
import json
import random
import time
import pdb
import asyncio
from concurrent.futures import ThreadPoolExecutor
from utils.utils import convert_time_us
from utils.generation import generation_post,generation_comment,general_generation,describe_active_provider
from utils.prompt import generate_paper_keywords_prompt
import argparse

TwitterBot.login_by_cookies = cookie_only_login_by_cookies


def apply_llm_cli_args(args):
    env_mapping = {
        "llm_provider": "LLM_PROVIDER",
        "chatgpt_api_key": "CHATGPT_API_KEY",
        "chatgpt_base_url": "CHATGPT_BASE_URL",
        "chatgpt_model": "CHATGPT_MODEL",
        "chatgpt_chat_model": "CHATGPT_CHAT_MODEL",
        "chatgpt_think_model": "CHATGPT_THINK_MODEL",
        "deepseek_api_key": "DEEPSEEK_API_KEY",
        "deepseek_base_url": "DEEPSEEK_BASE_URL",
        "deepseek_model": "DEEPSEEK_MODEL",
        "deepseek_chat_model": "DEEPSEEK_CHAT_MODEL",
        "deepseek_think_model": "DEEPSEEK_THINK_MODEL",
        "gemma_api_key": "GEMMA_API_KEY",
        "gemma_base_url": "GEMMA_BASE_URL",
        "gemma_model": "GEMMA_MODEL",
        "gemma_chat_model": "GEMMA_CHAT_MODEL",
        "gemma_think_model": "GEMMA_THINK_MODEL",
    }
    for arg_name, env_name in env_mapping.items():
        value = getattr(args, arg_name, None)
        if value not in (None, ""):
            os.environ[env_name] = value

class TwitterAgent():
    def __init__(self,log_path: str = "./logs/twitter/twitter_log.log"):
        self.log = logger(filename=log_path)
        self.database = sql_dataset('twitter')
        self.paper_agent = PaperAgent(platform='twitter', log_path="./logs/paperagent/paper_log.log")

    def get_all_account_ids(self):
        select_sql = "SELECT Account_id FROM accounts_info ORDER BY Account_id"
        results = self.database.get_dict_data_sql(select_sql)
        return [int(item["Account_id"]) for item in results if item.get("Account_id") is not None]

    async def get_account_character(self, account_id):
        default_character = '专心科研的学者，经常在社交平台发布论文相关的内容'
        try:
            search_sql = f"SELECT * FROM accounts_info WHERE accounts_info.Account_id = {account_id}"
            result = self.database.get_dict_data_sql(search_sql)
            if not result:
                return default_character

            character_id = result[0].get('Person_id')
            if not character_id:
                return default_character

            try:
                datebase = sql_dataset('twitter')
                character_sql = f"SELECT * FROM person WHERE person.Id = {character_id}"
                character_result = datebase.get_dict_data_sql(character_sql)
                if character_result and character_result[0].get("Description"):
                    return character_result[0]["Description"]
            except Exception as e:
                self.log.info(f"人设数据库不可用，账号{account_id}使用默认人设：{e}")

            return default_character
        except Exception as e:
            self.log.info(f"读取账号{account_id}人设失败，使用默认人设：{e}")
            return default_character

    def get_local_paper_candidates(self, paper_path=None):
        return self.paper_agent.get_local_paper_candidates(paper_path=paper_path)

    @staticmethod
    def _run_worker_sync(worker, kwargs):
        return asyncio.run(worker.auto_cultivation(**kwargs))

    async def build_paper_info(self, paper, domain):
        paper_info = {
            "Title": paper["Title"],
            "Abstract": paper.get("Abstract"),
            "URL": paper.get("URL"),
            "Gene_keywords": paper.get("Gene_keywords"),
            "Authors": paper.get("Authors"),
        }
        if not paper_info["Gene_keywords"] and paper_info["Abstract"]:
            keyword_text = await general_generation([
                {"role": "system", "content": generate_paper_keywords_prompt()},
                {"role": "user", "content": paper_info["Abstract"]},
            ])
            paper_info["Gene_keywords"] = [s.strip() for s in (keyword_text or "").split(",") if s.strip()]
        if not paper_info["Gene_keywords"]:
            paper_info["Gene_keywords"] = [domain]
        paper_info["image_paths"] = [paper["Image_path"]] if paper.get("Image_path") else []
        paper_info["Paper_id"] = paper.get("Paper_id")
        return paper_info

    @staticmethod
    def parse_account_ids(raw_account_ids):
        if not raw_account_ids:
            return []
        account_ids = []
        for item in str(raw_account_ids).split(","):
            item = item.strip()
            if not item:
                continue
            account_ids.append(int(item))
        return account_ids

    async def run_parallel_accounts(self, account_ids, news=True, followings=True, url=None, model=None, topic_path=None, force_run_now=False, paper_mode=False, domain=None, paper_path=None, max_cycles=None, max_runtime_minutes=None):
        self.log.info(f"准备并行运营账号: {account_ids}")
        tasks = []
        for account_id in account_ids:
            worker = TwitterAgent(log_path=f"./logs/twitter/{account_id}/twitter_log.log")
            worker_kwargs = {
                "account_ids": [int(account_id)],
                "news": news,
                "followings": followings,
                "url": url,
                "model": model,
                "topic_path": topic_path,
                "force_run_now": force_run_now,
                "paper_mode": paper_mode,
                "domain": domain,
                "paper_path": paper_path,
                "max_cycles": max_cycles,
                "max_runtime_minutes": max_runtime_minutes,
            }
            tasks.append(asyncio.to_thread(self._run_worker_sync, worker, worker_kwargs))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        for account_id, result in zip(account_ids, results):
            if isinstance(result, Exception):
                self.log.error(f"账号 {account_id} 并行运行失败: {result}")
                raise result
        return results

    async def get_action_time(self,account_ids,url=None,history=None,current_time=None,is_predict=True):
        accounts = []
        for account_id in account_ids:
            if account_ids.index(account_id) == 0:
                if is_predict:
                    planner = TwitterPlanner(log_path=f"./logs/twitter/{account_id}/twitter_log.log")
                    action_time = await planner.get_prediction_time(url=url,account_id=account_id,history=history)
                    self.log.info(f'''预测到{account_id}的操作时间为：{action_time}''')
                else:
                    search_sql = f"SELECT * FROM accounts_info WHERE accounts_info.Account_id = {account_id}"
                    result = self.database.get_dict_data_sql(search_sql)[0]
                    action_time = json.loads(result["Prediction_Action_Time"])
                date_time =current_time.strftime("%Y-%m-%d")
                for item in action_time:
                    if item["date"] == date_time:
                        accounts.append({f'{account_id}':item["detail"]})
                        break
            else:
                self.log.info(f'''预测到{account_id}的操作时间为：{action_time}''')
                # 更新数据库
                self.log.info(f"账号{account_id}预测的未来一周的活跃时间为：{action_time}")
                sql = '''UPDATE accounts_info SET Prediction_action_time = %s WHERE Account_id = %s'''
                self.database.operation(sql,(json.dumps(action_time),account_id,))
                self.log.info(f"更新数据库中账号{account_id}活跃时间成功")
                for item in action_time:
                    if item["date"] == date_time:
                        accounts.append({f'{account_id}':item["detail"]})
                        break
        self.log.info(f"获取到的账号操作时间为：{accounts}")
        
        return accounts

    
    async def auto_cultivation(self,account_ids,news=True,followings=True,url=None,model=None,topic_path=None,force_run_now=False,paper_mode=False,domain=None,paper_path=None,max_cycles=None,max_runtime_minutes=None):
        self.log.info(f'''开始培育账号:{account_ids}''')
        xingyun_flag = False
        should_force_run = force_run_now or os.environ.get("FORCE_RUN_NOW") == "1"
        if paper_mode:
            if should_force_run:
                os.environ["FORCE_RUN_NOW"] = "1"
                if max_cycles is None:
                    max_cycles = 1
            await self.paper_agent.auto_cultivation(
                account_ids=[int(account_id) for account_id in account_ids],
                domain=domain,
                paper_path=paper_path,
                max_cycles=max_cycles,
                max_runtime_minutes=max_runtime_minutes,
            )
            return
        if should_force_run and max_cycles is None:
            max_cycles = 1
        start_ts = time.monotonic()
        completed_cycles = 0
        #确认每个账号的操作时间没有过期
        while True:
            if max_runtime_minutes is not None and (time.monotonic() - start_ts) >= max_runtime_minutes * 60:
                self.log.info(f'已达到最大运行时长 {max_runtime_minutes} 分钟，自动退出')
                break
            if max_cycles is not None and completed_cycles >= max_cycles:
                self.log.info(f'已达到最大运行轮次 {max_cycles}，自动退出')
                break
            
            #利用一个账号获取检查所有的操作时间，如果时间为空或失效，重新预测时间
            search_sql = f"SELECT * FROM accounts_info WHERE accounts_info.Account_id = {account_ids[0]}"
            result = self.database.get_dict_data_sql(search_sql)[0]
            self.log.info(f'''获取到的账号信息为：{result}''')
            
            current_time = convert_time_us(datetime.now())
            self.log.info(f'''当前时间为：{current_time}''')
            
            if result["Prediction_Action_Time"] is None:
                planner = TwitterPlanner(log_path=f"./logs/twitter/{account_ids[0]}/twitter_log.log")
                history = await planner.get_history(account_id=account_ids[0],url=url) if url else None
                self.log.info(f'''获取到的历史信息为：{history}''')
                accounts = await self.get_action_time(account_ids,url=url,history=history,current_time=current_time)
                                   
            else:
                action_time = json.loads(result["Prediction_Action_Time"])
                #如果当前时间大于最后一次操作时，重新预测时间
                if current_time > datetime.strptime(action_time[-1]["date"], "%Y-%m-%d"):
                    planner = TwitterPlanner(log_path=f"./logs/twitter/{account_ids[0]}/twitter_log.log")
                    history = await planner.get_history(account_id=account_ids[0],url=url) if url else None
                    self.log.info(f'''获取到的历史信息为：{history}''')
                    accounts = await self.get_action_time(account_ids,url=url,history=history,current_time=current_time)
                else:
                    accounts = await self.get_action_time(account_ids,url=url,current_time=current_time,is_predict=False)
                    
            self.log.info(f'''账号的操作时间为：{accounts}''')
            planner = TwitterPlanner(log_path=f"./logs/twitter/{account_ids[0]}/twitter_log.log")
            accounts = planner.fomat_action_time(accounts)
            self.log.info(f'''规范化后的账号时间为：{accounts}''')#{"time":[id]}时间以小时计算
            # pdb.set_trace()
            while True:
                now_time = convert_time_us(datetime.now()).strftime("%H:%M")
                # now_time = '14:33'
                current_hour = now_time.split(":")[0]
                # 提取所有属于当前小时的时间点
                account_dict = {time:ids for time,ids in accounts.items() if time.split(":")[0] == current_hour}
                if should_force_run and not account_dict and accounts:
                    first_time = next(iter(accounts.keys()))
                    account_dict = {first_time: accounts[first_time]}
                    self.log.info("FORCE_RUN_NOW=1，跳过排班等待，立即执行当前账号")
                self.log.info(f'''当前时间为：{now_time}，当前小时的操作账号为：{account_dict}''')
                if account_dict:
                    # search_sql = f"SELECT * FROM accounts_info WHERE accounts_info.Account_id = {account_ids[0]}"
                    # result = self.database.get_dict_data_sql(search_sql)[0]
                    # character_id = result['Person_id']
                    # if character_id: # 获取人设
                    #     datebase = sql_dataset('agent')
                    #     character_sql = f"SELECT * FROM person WHERE person.Id = {character_id}"
                    #     character = datebase.get_dict_data_sql(character_sql)[0]["Description"]
                    # else:
                    #     character = None
                    planner = TwitterPlanner(log_path=f"./logs/twitter/{account_ids[0]}/twitter_log.log")
                    topics_informations,news_information,other_information = [],[],[]
                    if topic_path:
                        # 星云大师账号，从话题池中获取话题
                        topics_informations = await planner.get_topics_information(topic_path=topic_path)
                        # self.log.info(f'对于账户{account_dict}获取到的佛学话题为：{topics_informations}')
                    else:
                        # news_information, other_information = await planner.get_interested_information(account_id=int(account_ids[0]),news=news,followings=followings,url=url,characters=character)
                        # self.log.info(f'''对于账户{account_dict}获取到的感兴趣的新闻内容为：{news_information}''')
                        # self.log.info(f'''对于账户{account_dict}获取到的感兴趣的其他内容为：{other_information}''')
                        all_inforamtion = await planner.get_all_informations(account_id=int(account_ids[0]),news=news,followings=followings,url=url)
                        self.log.info(f'''对于账户{account_dict}获取到的信息是：{all_inforamtion}''')
                    
                    for time_key,ids in account_dict.items():
                        while True:
                            if should_force_run:
                                self.log.info(f'''FORCE_RUN_NOW=1，跳过时间 {time_key} 的等待，立即执行''')
                            elif now_time < time_key:
                                now_time = convert_time_us(datetime.now()).strftime("%H:%M")
                                self.log.info(f'''当前时间为：{now_time}，未到达操作时间：{time_key}''')
                                time.sleep(30)
                                continue

                            if topics_informations:
                                for account in ids:
                                    # 星云大师发帖
                                    character = await self.get_account_character(account_id=int(account))
                                    topic_information = random.sample(topics_informations,1)  # 随机选一个话题
                                    self.log.info(f'''对于账户{account}获取到的话题为：{topic_information[0]}''')
                                    content,response_time = await generation_post(text=topic_information[0],model=model,output_len=1000,character=character,language='中文繁体')
                                    content =  self.cut_content(content)
                                    self.log.info(f'要发布的内容是：{content}')
                                    bot = TwitterBot(log_path=f"./logs/twitter/{account}/twitter_log.log")  
                                    await bot.posts(account_id=int(account),content=content)
                                    bot.scroll(duration=random.uniform(20,40))
                                    bot.driver.quit()
                                    time.sleep(random.uniform(60,300))
                                time.sleep(1000)
                                xingyun_flag = True
                                break # 星云大师发完贴以后，结束掉循环

                            
                            for account in ids:
                                time.sleep(random.uniform(60,120))
                                character = await self.get_account_character(account_id=int(account))

                                # 根据账号人设判断该账号感兴趣的新闻/帖子
                                if all_inforamtion is None:
                                    self.log.info(f'未获取到任何有效信息，无法根据账号{account}的人设进行筛选')
                                    news_information, formation = [],[] # 定义两个空的列表
                                else:
                                    # 判断账号account感兴趣的内容
                                    self.log.info(f'根据账号{account}的人设：{character} 进行信息筛选')
                                    news_information, other_information = await planner.get_interested_information_for_account(account_id=int(account),all_information=all_inforamtion,characters=character)
                                    self.log.info(f'''对于账户{account}获取到的感兴趣的新闻内容为：{news_information}''')
                                    self.log.info(f'''对于账户{account}获取到的感兴趣的其他内容为：{other_information}''')

                                bot = TwitterBot(log_path=f"./logs/twitter/{account}/twitter_log.log")   # 初始化一个bot
                                self.log.info(f'开始登录账号{account}')
                                await bot.login_by_cookies(account_id=int(account))
                                time.sleep(random.uniform(30,60))
                                # 更新账号的user profile
                                await bot.get_user_profile(account_id=int(account))
                                bot.scroll(duration=random.uniform(10,20))
                                self.log.info(f'获取账号{account}关注的目标人物的五天之内的帖子')
                                try:
                                    target_informations = await planner.get_target_information(account_id=int(account),bot=bot)
                                    self.log.info(f'''对于账户{account}获取到的目标人物近五天的帖子信息是：{target_informations}''') 
                                    bot.scroll(duration=random.uniform(10,18))
                                except Exception as e:
                                    self.log.error(f'获取账号{account}关注的目标人物的帖子失败，错误信息：{e}')
                                    target_informations = []
                                # 定义两个标志位，用来判断是否发帖成功/转发成功
                                news_published = False
                                other_published = False

                                if len(news_information) != 0:
                                    # 发布新闻
                                    for published in news_information:
                                        action = "发帖"
                                        text = published["news"]  # 新闻话题
                                        # 发一个帖子
                                        content,response_time = await generation_post(text=text,model=model,output_len=1000,character=character,language='英文',style='informal')
                                        self.log.info(f'模型生成的发布内容是：{content}')
                                        # self.log.info(f'模型响应时间是：{response_time:.2f} 秒')
                                        content =  self.cut_content(content).replace('#','  ')
                                        self.log.info(f'经过字数检查之后要发布的内容是：{content}')
                                        if content == '':
                                            self.log.info(f'要发布的内容为空，选择下一个新闻内容进行发布')
                                            news_published = False
                                            continue
                                        await bot.posts(account_id=int(account),content=content)
                                        news_published = True # 表示发布成功
                                        break
                                bot.scroll(duration=random.uniform(10,18))
                                if len(other_information) != 0:
                                    # 转发/快转感兴趣的信息
                                    for published in other_information:
                                        #待发布内容的信息来源于url账号的关注列表
                                        action = random.choice(["转发","快转"])
                                        text = published["content"]  # 帖子内容
                                        # 检查数据库中是否已经存在
                                        sql = f'''SELECT * FROM twitter_interaction WHERE Account_id ={int(account)} AND URL = '{published["note_url"]}' AND Action = '{action}';'''
                                        select_result = self.database.get_dict_data_sql(sql)
                                        if select_result:
                                            continue
                                        if action == '转发':
                                            content,response_time = await generation_comment(text=text,model=model,output_len=200,character=character,language='英文',style='informal')
                                            self.log.info(f'模型生成的转发内容是：{content}')
                                            # self.log.info(f'模型响应时间是：{response_time:.2f} 秒')
                                            content =  self.cut_content(content).replace('#','  ')
                                            self.log.info(f'经过字数检查之后要转发的内容是：{content}')
                                            if content == '':
                                                self.log.info(f'要转发的内容为空，选择下一个新闻内容进行发布')
                                                other_published = False 
                                        elif action == '快转':
                                            content = None
                                        await bot.transmits(account_id=int(account),url=published["note_url"],content=content)
                                        other_published = True  # 表示操作成功
                                        break
                                # time.sleep(10)
                                bot.scroll(duration=random.uniform(10,20))  # 在页面随机滑动几秒

                                # 定义标志位，表示 是否评论/点赞成功
                                comment_published = False
                                like_published = False
                                published_break  = False
                                if (len(other_information) == 0 and len(news_information) == 0) or (not news_published and not other_published):  # 如果前边没有转发/发帖的话，则转发目标人物的一条帖子
                                    actions = ["点赞","评论","转发"]
                                    transmit_published = False    # 转发的标志位
                                else:  # 如果前边转发/发帖成功，则不再转发目标人物的帖子
                                    actions = ["点赞","评论"]
                                    transmit_published = True
                                if not target_informations:
                                    
                                    self.log.info(f'账号{account}没有关注任何目标人物，无法进行点赞/评论/转发操作')
                                    continue
                                for published in target_informations:
                                    # 重新定义 actions，点赞/评论/转发 不同的帖子
                                    actions = [action for flag, action in zip([like_published, comment_published, transmit_published],["点赞", "评论", "转发"]) if not flag]
                                    self.log.info(f'账号{account}要对目标人物的帖子进行的操作是：{actions}')
                                    if actions == []:
                                        self.log.info(f'账号{account}已经对目标人物的帖子进行过所有操作')
                                        break
                                    if 'content' not in published:
                                        continue
                                    text = published["content"]  # 帖子内容
                                    if published["note_url"] == 'Unknown':
                                        continue
                                    for action in actions:
                                        # 检查数据库中是否已经存在该操作
                                        sql = f'''SELECT * FROM twitter_interaction WHERE Account_id ={int(account)} AND URL = '{published["note_url"]}' AND Action = '{action}';'''
                                        select_result = self.database.get_dict_data_sql(sql)
                                        if select_result:
                                            self.log.info(f'账号{account}已经对该帖子{published["note_url"]}进行过{action}操作')
                                            published_break = True
                                            break 
                                        if action == '点赞':
                                            await bot.likes(account_id=int(account),url = published["note_url"])
                                            like_published = True # 表示点赞成功
                                            published_break = True
                                            break 
                                        elif action == '评论':
                                            content,response_time = await generation_comment(text=text,model=model,output_len=200,character=character,language='英文',style='informal')
                                            self.log.info(f'模型生成的评论内容是：{content}')
                                            content =  self.cut_content(content).replace('#','  ')
                                            self.log.info(f'经过字数检查之后要评论的内容是：{content}')
                                            if content == '':
                                                self.log.info(f'要评论的内容为空，选择下一个新闻内容进行发布')
                                                comment_published = False
                                                published_break = True
                                                break
                                            await bot.comments(account_id=int(account),url=published["note_url"],content=content)
                                            comment_published = True # 表示评论成功
                                            published_break = True
                                            break 
                                        elif action == '转发':
                                            content,response_time = await generation_comment(text=text,model=model,output_len=200,character=character,language='英文',style='informal')
                                            self.log.info(f'模型生成的转发内容是：{content}')
                                            content =  self.cut_content(content).replace('#','  ')
                                            self.log.info(f'经过字数检查之后要转发的内容是：{content}')
                                            if content == '':
                                                self.log.info(f'要转发的内容为空，选择下一个新闻内容进行发布')
                                                transmit_published = False
                                                published_break = True
                                                break
                                            await bot.transmits(account_id=int(account),url=published["note_url"],content=content)
                                            transmit_published = True # 表示转发成功
                                            published_break = True
                                            break
                                    time.sleep(random.uniform(10,18))
                                    if published_break:
                                        continue  # 找下一个记录
                                    # break
                                bot.scroll(duration=random.uniform(7,20))
                                bot.driver.driver.quit()   
                                
                            break
                        if xingyun_flag:
                            break # 结束掉当前时间点，等待下一个时间点
                    break

                else:
                    self.log.info(f'''当前时间为：{now_time}，未到达操作时间''')
                    time.sleep(300)  
            completed_cycles += 1
            self.log.info(f'结束循环，关闭运营')
            break
 
    
    
    def cut_content(self,content:str):
        '''如果长度大于280，则删除'''
        if len(content) >275:
            sentences = content.split('.')
            longest = ''
            for sentence in sentences:
                sentence = sentence.strip()  
                # 判断当前累积的句子和新句子的总长度是否小于270
                if len(longest) + len(sentence) + 1 <= 270:  # +1是为了加上句号
                    if longest:  
                        longest += sentence +'.' 
                    else:  
                        longest = sentence
                else:
                    break  # 如果添加新句子超过270
            content = longest
        return content
    


    def read_results_from_file(self,file_path):
        with open(file_path, "r", encoding="utf-8") as file:
            results = file.readlines()  
            results = [result.strip() for result in results]  # 去除每行末尾的换行符
        return results



    def select_random_results(self,results, min_count=20, max_count=30):
        # 随机选择 20 到 30 个名字
        count = random.randint(min_count, max_count)
        selected_results = random.sample(results, count)  # 从列表中随机选择不重复的元素
        return selected_results    
    
    
    async def auto_follow(self,account_ids,file_path):
        '''关注目标人物'''
        results = self.read_results_from_file(file_path=file_path)
        for account_id in account_ids:
            random_results = self.select_random_results(results=results)
            self.log.info(f'账号{account_id}要关注的目标账号是：{random_results}')
            self.log.info(f'登录账号{account_id}')
            bot = TwitterBot(log_path=f"./logs/twitter/{account_id}/target_log.log")  
            await bot.login_by_cookies(account_id=int(account_id)) # 登录一次，后边不需要再登录
            for result in random_results:
                await bot.follows(account_id=account_id,url=result)
                self.log.info(f'账号{account_id}成功关注目标账号：{result}')
                time.sleep(random.uniform(2,5))
            bot.modify_passwd(account_id=account_id)
            bot.driver.driver.quit()
            time.sleep(random.uniform(300,600))
        self.log.info(f'所有活跃账号成功关注20-30个目标人物')
    
    
    
    
    
    
            

        
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("--account-ids", default=os.environ.get("TWITTER_ACCOUNT_IDS"), help="逗号分隔的账号ID，例如 1,224")
    parser.add_argument("--force-run-now", action="store_true", help="忽略排班，立即执行")
    parser.add_argument("--news", action="store_true", default=False, help="抓取新闻素材")
    parser.add_argument("--followings", action="store_true", default=True, help="抓取关注列表素材")
    parser.add_argument("--no-followings", action="store_false", dest="followings", help="不抓取关注列表素材")
    parser.add_argument("--topic-path", default=os.environ.get("TWITTER_TOPIC_PATH", "./data/xingyundashi_topic.json"), help="话题池路径")
    parser.add_argument("--paper-mode", action="store_true", help="启用论文推荐模式，复用 paper_agent 的论文宣传流程")
    parser.add_argument("--domain", default=os.environ.get("TWITTER_DOMAIN", "Large Language Models for Recommendation"), help="论文领域")
    parser.add_argument("--paper-path", default=os.environ.get("TWITTER_PAPER_PATH"), help="本地论文 zip 目录")
    parser.add_argument("--max-cycles", type=int, default=None, help="最多运行多少轮后自动退出")
    parser.add_argument("--max-runtime-minutes", type=int, default=None, help="最多运行多少分钟后自动退出")
    parser.add_argument("--llm-provider", choices=["deepseek", "chatgpt", "openai", "gemma", "siliconflow"], help="LLM provider")
    parser.add_argument("--chatgpt-api-key", help="override CHATGPT_API_KEY")
    parser.add_argument("--chatgpt-base-url", help="override CHATGPT_BASE_URL")
    parser.add_argument("--chatgpt-model", help="override CHATGPT_MODEL")
    parser.add_argument("--chatgpt-chat-model", help="override CHATGPT_CHAT_MODEL")
    parser.add_argument("--chatgpt-think-model", help="override CHATGPT_THINK_MODEL")
    parser.add_argument("--deepseek-api-key", help="override DEEPSEEK_API_KEY")
    parser.add_argument("--deepseek-base-url", help="override DEEPSEEK_BASE_URL")
    parser.add_argument("--deepseek-model", help="override DEEPSEEK_MODEL")
    parser.add_argument("--deepseek-chat-model", help="override DEEPSEEK_CHAT_MODEL")
    parser.add_argument("--deepseek-think-model", help="override DEEPSEEK_THINK_MODEL")
    parser.add_argument("--gemma-api-key", help="override GEMMA_API_KEY")
    parser.add_argument("--gemma-base-url", help="override GEMMA_BASE_URL", default="https://api.siliconflow.com/v1")
    parser.add_argument("--gemma-model", help="override GEMMA_MODEL")
    parser.add_argument("--gemma-chat-model", help="override GEMMA_CHAT_MODEL")
    parser.add_argument("--gemma-think-model", help="override GEMMA_THINK_MODEL")
    args = parser.parse_args()
    apply_llm_cli_args(args)

    agent = TwitterAgent()
    llm_info = describe_active_provider()
    agent.log.info(
        f"Active LLM provider={llm_info['provider']}, "
        f"base_url={llm_info['base_url']}, "
        f"chat_model={llm_info['chat_model']}, "
        f"think_model={llm_info['think_model']}, "
        f"api_key={llm_info['api_key']}"
    )
    account_ids = agent.parse_account_ids(args.account_ids)
    if not account_ids:
        account_ids = agent.get_all_account_ids()[:2]
    if not account_ids:
        raise RuntimeError("No Twitter accounts found in accounts_info.")
    topic_path = args.topic_path
    if topic_path and not os.path.exists(topic_path):
        agent.log.info(f"话题池文件不存在，跳过 topic 模式: {topic_path}")
        topic_path = None
    asyncio.run(
        agent.run_parallel_accounts(
            account_ids=account_ids,
            news=args.news,
            followings=args.followings,
            model='Xingyun',
            topic_path=topic_path,
            force_run_now=args.force_run_now,
            paper_mode=args.paper_mode,
            domain=args.domain,
            paper_path=args.paper_path,
            max_cycles=args.max_cycles,
            max_runtime_minutes=args.max_runtime_minutes,
        )
    )


            

            

