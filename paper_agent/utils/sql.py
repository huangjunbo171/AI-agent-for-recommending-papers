import pymysql
from pymysql import OperationalError
from config import DATABASE_INFO

class sql_dataset():

    def __init__(self, dataset_name: str = None):
        # self.dataset_name = DATABASE_INFO["DB_NAME"] # 数据库名字
        self.dataset_name = dataset_name
        self.conn = None
        self.cursor = None


    def connect(self):
        """获取数据库连接"""
        self.conn = pymysql.connect(
            host=DATABASE_INFO["HOST"],		    # 主机名（或IP地址）
            port=int(DATABASE_INFO["PORT"]),			# 端口号，默认为3306
            user=DATABASE_INFO["USER"],			 # 用户名
            password=DATABASE_INFO["PASSWORD"], 	# 密码
            charset='utf8mb4'  		# 设置字符编码
        )
        self.cursor = self.conn.cursor()
        self.conn.select_db(self.dataset_name)


    def get_index_dict(self):
        """
        获取数据库对应表中的字段名
        """
        # try:
            # self.connect()  # 重新连接数据库
        index_dict=dict()
        index=0
        for desc in self.cursor.description:
            index_dict[desc[0]]=index
            index=index+1
        return index_dict
        # finally:
        #     self.close_dataset() # 关闭数据库
        
    def get_dict_data_sql(self,sql):
        """
        运行sql查询语句，获取结果，并根据表中字段名，转化成dict格式（默认是tuple格式）
        """
        
        try:
            self.connect()  # 重新连接数据库
            self.cursor.execute(sql)
            data = self.cursor.fetchall()
            index_dict=self.get_index_dict()
            res=[]
            for datai in data:
                resi=dict()
                for indexi in index_dict:
                    resi[indexi]=datai[index_dict[indexi]]
                res.append(resi)
            return res
        finally:
            self.close_dataset()

    def close_dataset(self):
        if self.cursor:
            self.cursor.close()
            self.cursor = None
        if self.conn:
            self.conn.close()
            self.conn = None

    def operation(self,sql,data_turple=None):
        try:
            self.connect()  # 重新连接数据库
            if data_turple:
                self.cursor.execute(sql, data_turple)
            else:
                self.cursor.execute(sql)
            self.conn.commit()
        finally:
            self.close_dataset()

    def insert_role_data(self,data,usable=1):
        #默认插入的人设数据可用
        self.connect()  # 重新连接数据库
        name = data["name"]
        age = int(data["age"])
        gender = data["gender"]
        country = data["country"]
        area = data["area"]
        language = data["language"]
        job = data["job"]
        field = str(data["field"])
        interest = str(data["interest"])
        party = data["party"]
        party_content = data["party_content"]
        description = data["description"]
        style = data["style"]
        opinion = str(data["opinion"])
        education = data["education"]
        character = data["character"]
        marriage = data["marriage"]
        # usable = usable
        
        self.cursor.execute('''INSERT IGNORE `person` (`Name`, `Age`, `Gender`, `Country`, `Area`, `Language`, `Job`, `Party`, `Party_Content`, `Field`, `Interest`, `Character`, `Marriage`, `Education`, `Opinion`, `Description`, `Style`) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                              (name, age,gender, country,area,language, job,party,party_content,field,interest,character,marriage,education,opinion,description,style))
        self.conn.commit()


