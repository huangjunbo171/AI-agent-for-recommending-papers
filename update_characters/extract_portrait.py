import os
import sys
pythonpath = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0,pythonpath)
import subprocess
os.environ.pop("SSL_CERT_FILE", None)
try:
    from sentence_transformers import SentenceTransformer
    from sentence_transformers import util
except ImportError:
    SentenceTransformer = None
    util = None
import json
import numpy as np
import pandas as pd
from sklearn.cluster import AgglomerativeClustering
from utils.prompt import extract_field_prompt,extract_interest_prompt,extract_view_prompt,extract_topic_prompt,summary_topic_content
from utils.log import logger
import asyncio
from typing import Optional,Union
from utils.generation import general_generation,generation_post
import re
from  utils.sql import sql_dataset
import pdb


# 构造platform和数据库的映射
platform_to_db = {
    "twitter": "twitter",
    "facebook": "facebook",
    "xiaohongshu": "xiaohongshu",
    "weibo": "weibo",
    "kuaishou": "kuaishou",
    "douyin": "douyin",
    "toutiao": "toutiao",
    "bilibili": "bilibili"
}

field_list = ["法律","军事","经济","政治","科技","宗教","教育","医疗","娱乐","体育","美食","其他"]  # 领域
interest_list=['游戏',"美妆","运动健身","动漫","音乐演出","军事","财经","美食","汽车","动物宠物","政治","摄影","教育","宗教","影视剧","旅游","数码","科技科幻","星座","文化读书","笑话小品","法律","公益"]

parties = {
           "美国民主党":"民主党人主张社会公平、经济平等和环境保护，倡导减少贫困、提高工资、改善医疗保健，支持提高税收和增加公共支出，主张加强环保措施和减少碳排放，医疗保健改革是重点议题，追求更普惠的医疗保障系统。在移民政策上，民主党人倾向于支持更宽松的政策，包括提供合法途径供移民融入社会，主张平等和多元文化，支持LGBTQ+权益、女性权益和少数族裔权益，主张加强环保措施和减少碳排放，主张对外合作和多边主义，强调国际组织和法律的重要性，支持国际组织和外交谈判解决问题。此外，民主党强调民权、种族平等和性别平等，支持立法和政策以消除歧视",
           "美国共和党":"共和党人通常倾向于保守主义，关注经济发展和个人责任，主张减少政府干预，支持减税和降低支出以促进经济增长。共和党人强调个人自由和企业创新，倡导在市场中解决问题，主张私有化医疗保健系统以增加选择权。在移民政策上，倾向于支持更严格的边境控制和移民法律执行，强调国家安全和法治。共和党强调家庭价值观和传统，通常支持传统的婚姻定义，强调宗教自由权。他们通常更强调国家主权和自给自足，偏向于双边主义而非多边主义，更加强调美国利益优先和强大的国防。在环境政策上，共和党人对环保措施持谨慎态度，强调经济发展和就业机会的重要性。同时，共和党也关注民权，但可能强调个人责任和社区解决问题的能力",
           "民主进步党":"以 “台湾主体性” 为核心，主张 “台独” 路线，强调 “本土优先” 与社会多元价值。在社会福利方面推动 “长照 2.0” 计划，但因财政压力面临资金缺口；经济上提出 “前瞻基础建设” 计划，增加公共支出以刺激就业，但被批评独厚大企业，加剧南北发展失衡。在能源政策上坚持 2025 年全面废核目标，关闭 “核二厂”，扩大天然气发电占比至 50% 以上，但导致空气污染加剧；承诺 2050 年达成 “净零排放”，推动绿能补贴政策，但绿能投资效率低下。医疗保健方面，2022 年调高健保费率至 4.69%，并调整急诊、药品自付额，引发民众抗议。移民政策上，延长陆配取得身份证年限至 6 年（外籍配偶为 4 年），并限制其参与政治活动，强化 “两岸对立” 叙事。LGBTQ + 权益方面，推动同性婚姻合法化，但 2018 年 “反同公投” 挫败后，政策推进放缓。对外政策上，强化对美军事合作，2025 年度防务预算达 6,068 亿新台币，采购 F-16V 等先进武器；推动 “参与联合国” 等 “台独” 外交议题，试图以 “非官方身份” 加入国际组织。",
           "中国国民党":"以 “三民主义” 为基础，主张 “九二共识” 与两岸和平发展，强调传统价值观。经济政策上主张降低企业税至 15%，吸引台商回流，但被批评 “独厚财团”；推动 “青年住宅政策”，提供购房补贴，但效果有限，青年失业率仍高于整体水平。能源政策上主张延长核电厂执照至 60 年，修改 “环境基本法” 为 “非碳家园”，以核能替代燃煤发电；批评民进党 “非核家园” 导致火力发电依赖，但缺乏具体减排方案。医疗保健方面反对民进党调高健保费率及自付额，主张通过 “开源节流”（如打击医疗浪费）维持健保财务平衡；推动 “长照保险法”，将长照预算制改为保险制，以解决财政缺口。移民政策上支持缩短陆配取得身份证年限至 4 年，与外籍配偶一致，批评民进党 “歧视性政策”。LGBTQ + 权益方面反对同性婚姻入 “民法”，主张另立 “专法” 保障同性伴侣权益，2018 年 “反同公投” 中获支持。对外政策上坚持 “九二共识”，主张恢复两岸制度化协商，扩大经贸合作（如重启服贸协议）；强调 “亲美友日”，但主张 “不挑衅、不冲突”，避免过度刺激大陆。",
           "台湾民众党":"以 “超越蓝绿” 为口号，主张技术官僚治理，吸引中间选民。经济上提出 “普发现金 6,000 元”，并将超征税收拨补健保基金，获 65% 民众支持；推动 “青年创业贷款”，但资金规模有限，效果未达预期。能源政策上支持可再生能源，但未明确废核时间表，主张 “弹性能源政策”；批评民进党治理不力，但缺乏具体解决方案。医疗保健方面要求公开高端疫苗采购信息，主张 “阳光法案” 防止利益输送；未提出系统性健保改革方案，倾向 “微调” 现有制度。移民政策上支持缩短陆配取得身份证年限至 4 年，主张 “消除歧视”；关注东南亚移工权益，但内部因派系争议（如徐瑞希退党事件）导致政策摇摆。LGBTQ + 权益方面支持同性婚姻合法化，但未积极推动立法，被批评 “口号多于行动”。对外政策上主张 “台湾自主、两岸和平”，反对明确接受 “九二共识”，强调 “对话减少敌意”；寻求 “务实外交”，但缺乏具体突破。",
           "亲民党":"以 “人民第一” 为宗旨，主张 “两岸一中” 与民生优先。关注贫富差距，主张扩大社会福利（如提高老农津贴），但因党员人数少，影响力有限；支持两岸共同市场，推动陆资入台，但遭民进党阻挠。在能源和医疗政策上无明确主张，倾向跟随主流论述。移民政策上支持陆配权益，主张两岸交流，但缺乏政策推动。LGBTQ + 权益方面无明确立场，未公开支持或反对同性婚姻，立场模糊。对外政策上主张 “九二共识”，支持平等协商统一，但缺乏实际行动；强调 “务实外交”，但影响力有限。",
           "新党":"最坚定的统派政党，主张 “一国两制台湾方案”。主张打击贪腐，推动 “阳光法案”，但因边缘化难以落实；支持财富重分配，缩小贫富差距，但缺乏具体政策。在能源和医疗政策上无明确主张。移民政策上主张统一后两岸自由流动，陆配权益与台湾民众一致。LGBTQ + 权益方面无明确立场，未公开支持或反对同性婚姻，立场保守。对外政策上主张 “一国两制”，支持台湾作为特别行政区，停止对美军购；反对 “台独” 外交，主张以 “中国台湾” 名义参与国际组织。"
           }

# 构造映射
key_function_map = {
    "interest": extract_interest_prompt,
    "field": extract_field_prompt,
    "topic": extract_topic_prompt
}


# 模型的本地路径
EMBEDDING_MODEL_PATH = os.environ.get("EMBEDDING_MODEL_PATH", r'D:\code\qwen-4b\gte-large-zh')

class AccountPortrait():
    def __init__(self, data:list[dict],platform:str=None,account_id=None,interest_list:list=None,language='英文') -> None:   #  embedding_path = EMBEDDING_MODEL_PATH
        #name:评测账号姓名
        #eval_data_path: 评测账号贴文数据
        self.log = logger(filename='./logs/update_character/extract.log')
        if SentenceTransformer is None or util is None:
            raise ImportError(
                "Missing dependency 'sentence-transformers'. "
                "Install it with 'python -m pip install sentence-transformers'."
            )
        if not os.path.exists(EMBEDDING_MODEL_PATH):
            raise FileNotFoundError(
                f"Embedding model path not found: {EMBEDDING_MODEL_PATH}. "
                "Set environment variable EMBEDDING_MODEL_PATH to your local model directory."
            )
        self.embeddingmodel = SentenceTransformer(EMBEDDING_MODEL_PATH)
        self.portrait = {}
        self.account_id = account_id
        self.data = self._wrap_content(data)
        if platform:
            self.database_name = platform_to_db[platform]
            self.database = sql_dataset(self.database_name)
        # self.account_id = account_id
        self.interest_list = interest_list if interest_list is not None else globals()['interest_list'], 
        self.list_to_key = {
                "interest": self.interest_list,
                "field":field_list,
                "topic":[]
            }
        self.language  = language


    def _wrap_content(self, data):
        '''数据转换，处理str、list[str]、list[dict]三种形式'''
        if isinstance(data, str):
            return [{"content": data}]
        elif isinstance(data, list):
            if all(isinstance(item, str) for item in data):
                # 处理列表中的每个元素是字符串的情况
                return [{"content": c} for c in data if c.strip()]
            
            elif all(isinstance(item, dict) for item in data):
                # 处理列表中的每个元素是字典的情况，提取content字段
                # return [{"content": item.get("content")} for item in data if isinstance(item, dict) and "content" in item]
                return data
            else:
                raise ValueError("list中的元素必须是字符串或字典")
        else:
            raise ValueError("data 参数必须是 str 或 list[str] 或 list[dict]")   
    

    async def generate_key(self,key:str=None):
        '''对每一个贴文content提取兴趣或者领域或者观点立场'''
        key_results = []
        for index, post in enumerate(self.data):
            if "content" not in post or not post["content"]:
                continue
            if key in ["topic","field","interest"]:  # 提取帖子的兴趣、领域、观点和立场
                response_result = await general_generation([{"role":"system","content":key_function_map[key](self.list_to_key[key],self.language)},{"role":"user","content": post["content"]}]) # 提取兴趣和领域
                # try:
                #     response_result,_ = await generation_post(text= key_function_map[key](self.list_to_key[key],self.language,post["content"]),model="Qwen2.5-14b-Instruct")  # 14B
                # except:
                #     self.log.error(f"第{index}行生成{key}错误，原始贴文为：{post['content']}")
                #     continue
                # 对结果进行后处理
                if not response_result or 'none' in response_result.lower():
                    r =  []
                else:
                    r = re.split(r'[，,]', response_result)
            elif key == 'view':
                response_result = await general_generation([{"role":"system","content":extract_view_prompt(language=self.language)},{"role":"user","content": post["content"]}])  # 提取 观点和立场
                # try:
                #     response_result,_ = await generation_post(text= extract_view_prompt(self.language,post["content"]),model="Qwen2.5-14b-Instruct")  # 14B
                # except:
                #     self.log.error(f"第{index}行生成{key}错误，原始贴文为：{post['content']}")
                #     continue

                # 对结果进行后处理
                if not response_result or 'none' in response_result.lower():
                    r = []
                else:
                    matches = re.findall(r'<([^,]+),\s*(.*?)>', response_result)
                    r = [{"opinion": match[0], "stand": match[1]} for match in matches]  # 转换成[{"opinion": "xxx", "stand": "xxx"}]
            else:
                self.log.info("键值未找到，重新输入key")
                break
            self.log.info(f"第{index}行生成{key}为:{r}，原始贴文为：{post['content']}")
            self.data[index][key] = r 
            if self.account_id: # 更新到数据库中
                self.update_one_data(post=post,key=key,value=r)  # 更新数据库中 ，该条数据的 观点立场/兴趣/领域
            
        # if not self.account_id:
        #     return self.data   # 返回

            

    def update_one_data(self,post:dict,key:str,value:list):
        '''更新交互表中的贴文的兴趣、领域和观点立场'''
        info_to_key = {"view": "Opinion_stand", "field": "Field", "interest": "Interest"}
        update_sql = f'''UPDATE {self.database_name}_interaction SET {info_to_key[key]} = %s WHERE Account_id = %s AND URL = %s AND Action = %s'''
        self.database.operation(update_sql,(str(value),self.account_id,post["url"],post["action"]))
        self.log.info(f'已成功更新 交互表 中一条帖子的 {info_to_key[key]} 字段')
    
    
    async def _clustering(self,key,key_data_list,data_list,threshold):
        #key:选择聚类的key
        embeddings = self.embeddingmodel.encode(key_data_list)
        similarity_matrix = util.pytorch_cos_sim(embeddings, embeddings)

        clustering = AgglomerativeClustering(n_clusters=None, metric='precomputed', linkage='average', distance_threshold=threshold)
        labels = clustering.fit_predict(1 - similarity_matrix.numpy())
        merged_data = {}
        for idx, label in enumerate(labels):
            if label not in merged_data:
                merged_data[label] = {key: [], "contents": []}
            merged_data[label][key].append(key_data_list[idx])
            merged_data[label]["contents"].append(data_list[idx])
        # for merged in merged_data.values():
        #     print(merged[key])
        # cluster_label = []
        # for merged in merged_data.values():
        #     response= await general_generation([{"role":"system","content":summary_topic_content("","")},{"role":"user","content": ''.join(merged[key]) + self.language}]) 
        #     print(f'模型总结的{key}内容是：{response}')
            # cluster_label.append()
            # print(f'提取出来的主要{key}是：{cluster_label}')

        cluster_label =  [await general_generation([{"role":"system","content":summary_topic_content(language=self.language)},{"role":"user","content": ''.join(merged[key])}]) for merged in merged_data.values()]
        # cluster_label =  [await generation_post(text=summary_topic_content(language=self.language,content=''.join(merged[key])),language=self.language,model="Qwen2.5-14b-Instruct") for merged in merged_data.values()]
        
        # print(f'模型的总结内容是：{cluster_label}')
        # cluster_label = [await summary_cluster(merged[key]) for merged in merged_data.values()]
        cluster_result = [{"total":label, key: merged[key], "content": merged["contents"]} for merged,label in zip(merged_data.values(),cluster_label)]
        return cluster_label,cluster_result


    async def extract_main_key(self,key,threshold:float=0.4):
        '''根据每条贴文的兴趣、话题等，进行聚类，提取主要的兴趣、话题'''
        df_ori = pd.DataFrame(self.data)
        df_key = df_ori[df_ori[key]!=""]
        df_key = df_key.dropna(axis=0,subset=[key])
        keys = df_key[key].to_list()
        key_data = df_key.to_dict("records")
        # 查看topic的类型
        # print(topic_data,type(topic_data))
        # 将topics转换成[str]
        filtered_keys = [item for item in keys if not (len(item) == 1 and item[0] == '[]')]
        key_data_list = [", ".join(item) for item in filtered_keys]
        # pdb.set_trace()
        # 如果只有一个元素，则不需要聚类
        if len(key_data_list) < 2:
            self.log.info(f"提取主要{key}: {key_data_list}")
            return key_data_list

        results,key_cluster_result = await self._clustering(key,key_data_list,key_data,threshold)
        # # if len(topics)>5:
        # if len(key_data_list) >  5:
        #     results,key_cluster_result = await self._clustering(key,key_data_list,key_data,threshold)
        # else:
        #     key_cluster_result = [{"total":data[key], key: data[key], "content": data} for data in key_data]
        # self.topics = results
        setattr(self, key, results)
        self.log.info(f"提取主要{key}: {results}")
        return results
        
    


    async def extract_field(self):
        '''提取主要的关注领域，'''
        ###用pandas提取每个关注领域贴文数量
        df = pd.DataFrame(self.data)
         # 过滤掉那些没有'field'的记录
        df_field = df[df['field'].notna() & (df['field'] != "")]
       
        df_field = df_field.explode('field')
    
        result,fields = [],[]
        for field in field_list:
            contains_field = df_field['field'].str.contains(field, na=False)
            count = contains_field.sum()
            result.append({"field":field,"count":int(count)})
            if count> int(len(df_field)/20):
                fields.append(field)
        sorted_result = sorted(result, key=lambda x: x["count"], reverse=True)
        top_3_fields = [item["field"] for item in sorted_result[:3] if item["field"] in fields]
        self.fields = top_3_fields
        self.log.info(f"提取主要关注领域：{top_3_fields}")
        self.fields_result = result
        self.top_fields = top_3_fields

    


    async def extract_interest(self):
        '''提取主要的兴趣，'''
        ###用pandas提取每个关注领域贴文数量
        df = pd.DataFrame(self.data)
         # 过滤掉那些没有'interest'的记录
        df_interest = df[df['interest'].notna() & (df['interest'] != "")]
       
        df_interest = df_interest.explode('interest')
    
        result,interests = [],[]
        for interest in self.interest_list:
            contains_interest = df_interest['interest'].str.contains(interest, na=False)
            count = contains_interest.sum()
            result.append({"interest":interest,"count":int(count)})
            if count> int(len(df_interest)/20):
                interests.append(interest)
        sorted_result = sorted(result, key=lambda x: x["count"], reverse=True)
        top_3_interests = [item["interest"] for item in sorted_result[:3] if item["interest"] in interests]
        self.interests = top_3_interests
        self.log.info(f"提取主要兴趣：{top_3_interests}")
        self.interests_result = result
        self.top_interests = top_3_interests
    
    async def extract_view_stand(self):
        '''提取观点和立场，保留content和view'''
        self.view = [{"content": item["content"], "view":item["view"]} for item in self.data ]
        self.log.info(f"提取帖子的观点和立场是：{self.view}")


    

async def extract_portrait(data):
    '''
    提取每一条贴文的观点，然后根据一周的观点 提取 兴趣和领域
    '''
    e = AccountPortrait(data=data) # 传入一周内的贴文数据，list
    await e.generate_key(key = 'view')  # 提取每条贴文的观点和立场
    await asyncio.gather(e.generate_key(key = 'interest'),e.generate_key(key = 'field'))  # 提取每条贴文的兴趣和领域
    await asyncio.gather(e.extract_interest(),e.extract_field())  # 对兴趣爱好和领域进行聚类，最后得到一个兴趣、领域，拿去更新人设表
    e.portrait = {"top_interests":e.top_interests,"top_fields":e.top_fields,"content_view_field": [{"content":item["content"],"view":item["view"],"field":item["field"]} for item in e.data]}   # content_view_filed 是每个贴文对应的观点立场和领域，要更新到交互表中

    return e.portrait
