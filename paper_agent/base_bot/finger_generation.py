
import os
import json
import random
from typing import Dict, List


'''为每一个twitter账号生成浏览器指纹'''
class BrowserFingerprintGenerator:
    """浏览器指纹生成器，每个实例生成唯一指纹"""
    # 预设指纹池
    # 浏览器UA
    _UA_POOL = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 11.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 15_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
    ]
    # 其他指纹属性池（删除window_size池）
    _TIMEZONE_POOL = ["America/New_York", "America/Los_Angeles", "America/Chicago", "America/Denver", "America/Miami"]
    _PLATFORM_POOL = ["Win32", "MacIntel", "Linux x86_64"]
    _PLUGINS_POOL = [[1,2,3], [1,2,3,4], [2,3,5], [1,3,4], [2,4]]
    # _PROFILE_ROOT = "./information/chrome_profiles"

    @classmethod
    def generate_single_fingerprint(cls, account_id) -> Dict:
        """
        生成单个唯一指纹，返回字典
        """
        # 为每个账号生成唯一的profile路径：./chrome_profiles/account_{account_id}
        profile_path = f"./information/chrome_profiles/account_{account_id}"
        
        return {
            "user_agent": random.choice(cls._UA_POOL),
            "platform": random.choice(cls._PLATFORM_POOL),
            "languages": ["en-US", "en"],   # 语言固定为美式英文
            "plugins": random.choice(cls._PLUGINS_POOL),
            "timezone": random.choice(cls._TIMEZONE_POOL),
            "device_pixel_ratio": random.choice([1, 1.5, 2]),  # 像素比 
            "hardware_concurrency": random.choice([4, 6, 8]),   # CPU核心数
            "profile_path": profile_path  # 新增：账号专属Chrome配置目录
        }

    @classmethod
    def generate_batch_fingerprint(cls, account_ids:list) -> Dict:
        """批量生成指纹，与账号ID绑定 ,，且保证指纹不重复"""
        account_fingerprint = {}
        generated_keys = set()  # 去重关键

        for account_id in account_ids:
            # 循环直到生成不重复的指纹
            while True:
                fp = cls.generate_single_fingerprint(account_id)
                # 生成唯一key（删除window_size，新增profile_path不参与去重，因为和account_id绑定唯一）
                fp_key = (
                    fp["user_agent"],
                    fp["platform"],
                    fp["timezone"],
                    fp["hardware_concurrency"],
                    fp["device_pixel_ratio"]
                )
                if fp_key not in generated_keys:
                    generated_keys.add(fp_key)
                    account_fingerprint[account_id] = fp
                    break

        return account_fingerprint




class FingerprintPersistence:
    """指纹持久化，支持JSON文件"""

    @staticmethod
    def save_to_json(fingerprint_data: Dict, file_path: str = "./data/account_fingerprints.json"):
        """
        追加保存，自动处理空文件、损坏文件，永不报错
        """
        old_data = {}

        if os.path.exists(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if content:  
                        old_data = json.loads(content)
            except json.JSONDecodeError:
                old_data = {}
        merged_data = {**old_data, **fingerprint_data}
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(merged_data, f, ensure_ascii=False, indent=4)

        print(f"合并保存成功！总计账号数：{len(merged_data)}")



    @staticmethod
    def load_from_json(file_path: str = "./data/account_fingerprints.json") -> Dict[int, Dict]:
        """从JSON文件读取指纹，返回{账号ID:指纹}"""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"指纹文件不存在：{file_path}，请先批量生成并保存")
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # 把JSON中的字符串key转回整数账号ID
        return {int(account_id): fp for account_id, fp in data.items()}



if __name__ == "__main__":
    account_ids = [
        # 8,9,45,46,47,48,
        # 50,51,52,54,55,57,58,59,60,61,62,63,64,65,66,67,69,70,71,72,73,74,75,76,77,78,79,80,81,
        # 140,141,142,143,144,145,146,147,148,149,150,151,152,153,154,155,157,158,160,
        # 161,162,163,164,166,167,168,169,170,171,172,173,174,175,176,177,178,179,180,
        # 181,182,183,184,185,186,187,188,189,190,191,192,193,
        # 210,217,218,219,220,221,222
        139
    ]
    generator = BrowserFingerprintGenerator()
    fingerprints = generator.generate_batch_fingerprint(account_ids)
    FingerprintPersistence.save_to_json(fingerprints)
    print('指纹生成并保存完成！')


