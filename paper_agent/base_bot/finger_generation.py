import json
import os
import random
from typing import Dict


class BrowserFingerprintGenerator:
    """Generate a stable browser fingerprint for each account."""

    _PROFILE_ROOT = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "information", "chrome_profiles")
    )
    _UA_POOL = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 11.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 15_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    ]
    _TIMEZONE_POOL = [
        "America/New_York",
        "America/Los_Angeles",
        "America/Chicago",
        "America/Denver",
        "America/Miami",
    ]
    _PLUGINS_POOL = [[1, 2, 3], [1, 2, 3, 4], [2, 3, 5], [1, 3, 4], [2, 4]]

    @staticmethod
    def _platform_from_user_agent(user_agent: str) -> str:
        ua = (user_agent or "").lower()
        if "macintosh" in ua or "mac os x" in ua:
            return "MacIntel"
        if "linux" in ua:
            return "Linux x86_64"
        return "Win32"

    @classmethod
    def generate_single_fingerprint(cls, account_id) -> Dict:
        user_agent = random.choice(cls._UA_POOL)
        profile_path = os.path.join(cls._PROFILE_ROOT, f"account_{account_id}")

        return {
            "user_agent": user_agent,
            "platform": cls._platform_from_user_agent(user_agent),
            "languages": ["en-US", "en"],
            "plugins": random.choice(cls._PLUGINS_POOL),
            "timezone": random.choice(cls._TIMEZONE_POOL),
            "device_pixel_ratio": random.choice([1, 1.5, 2]),
            "hardware_concurrency": random.choice([4, 6, 8]),
            "profile_path": profile_path,
        }

    @classmethod
    def generate_batch_fingerprint(cls, account_ids: list) -> Dict:
        account_fingerprint = {}
        generated_keys = set()

        for account_id in account_ids:
            while True:
                fp = cls.generate_single_fingerprint(account_id)
                fp_key = (
                    fp["user_agent"],
                    fp["platform"],
                    fp["timezone"],
                    fp["hardware_concurrency"],
                    fp["device_pixel_ratio"],
                )
                if fp_key not in generated_keys:
                    generated_keys.add(fp_key)
                    account_fingerprint[account_id] = fp
                    break

        return account_fingerprint


class FingerprintPersistence:
    """Persist fingerprints in JSON."""

    @staticmethod
    def save_to_json(fingerprint_data: Dict, file_path: str = "./data/account_fingerprints.json"):
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

        print(f"合并保存成功，总账号数：{len(merged_data)}")

    @staticmethod
    def load_from_json(file_path: str = "./data/account_fingerprints.json") -> Dict[int, Dict]:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"指纹文件不存在：{file_path}，请先批量生成并保存")
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {int(account_id): fp for account_id, fp in data.items()}


if __name__ == "__main__":
    account_ids = [1, 224]
    generator = BrowserFingerprintGenerator()
    fingerprints = generator.generate_batch_fingerprint(account_ids)
    FingerprintPersistence.save_to_json(fingerprints)
    print("指纹生成并保存完成")
