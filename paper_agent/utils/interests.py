from utils.sql import sql_dataset
import requests


def get_character(account_id,person_id,database):
    characters = None
    if not person_id:
        sql = f"SELECT Person_id FROM accounts_info WHERE Account_id = '{account_id}'"
        personid = database.get_dict_data_sql(sql)[0]["Person_id"] if database.get_dict_data_sql(sql) else None
        if personid:
            character_sql = f"SELECT Description FROM person WHERE person.Id = '{person_id}'"
            characters = database.get_dict_data_sql(character_sql)[0]["Description"] if database.get_dict_data_sql(character_sql) else None
        else:
            characters = None
    else:
        database = sql_dataset('kejibu')
        sql = f"SELECT * FROM account_info WHERE id = {person_id}"
        results = database.get_dict_data_sql(sql)[0] if database.get_dict_data_sql(sql) else None       
        characters = results['Interest']
    return characters




async def interest_detection(account_id,characters,content,database):
    
    history_sql = f"SELECT Account_id, Content FROM {database.dataset_name}_interaction WHERE Account_id = '{account_id}' AND Action = '点赞'"
    histories = database.get_dict_data_sql(history_sql)
    data = {"user_samples":histories[:10],"interests":[characters],'content':content}
    response = requests.post("http://172.16.32.11:30400/detect_behavior",json=data).json()
    result = response['response'][0].split('Generated text:')[-1]
    result = result.replace('\n','').replace('\'','').replace(' ','')
    return result


    

