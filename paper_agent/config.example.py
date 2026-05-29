import os

# Copy this file to config.py and fill in local values.
# config.py is ignored by git because it may contain API keys, database
# passwords, proxy credentials, and local driver paths.

DEFAULT_DRIVER_PATH = os.environ.get("DEFAULT_DRIVER_PATH", "")
KEY_WORDS_PATH = os.environ.get("KEY_WORDS_PATH", "./checklist_files/baijiahao_keywords.txt")

DEEPSEEK_INFO = {
    "API_KEY": os.environ.get("DEEPSEEK_API_KEY", ""),
    "BASE_URL": os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
    "MODEL": os.environ.get("DEEPSEEK_MODEL", "deepseek-reasoner"),
    "CHAT_MODEL": os.environ.get("DEEPSEEK_CHAT_MODEL", "deepseek-chat"),
    "THINK_MODEL": os.environ.get("DEEPSEEK_THINK_MODEL", "deepseek-reasoner"),
    "TEMPERATURE": 1.0,
    "TOP_P": 1.0,
    "MAX_TOKEN": 8192,
    "PRESENCE_PENALTY": 0.0,
}

CHATGPT_INFO = {
    "API_KEY": os.environ.get("CHATGPT_API_KEY", ""),
    "BASE_URL": os.environ.get("CHATGPT_BASE_URL", "https://api.openai.com/v1"),
    "MODEL": os.environ.get("CHATGPT_MODEL", "gpt-4.1"),
    "CHAT_MODEL": os.environ.get("CHATGPT_CHAT_MODEL", "gpt-4.1-mini"),
    "THINK_MODEL": os.environ.get("CHATGPT_THINK_MODEL", "gpt-4.1"),
    "TEMPERATURE": 1.0,
    "TOP_P": 1.0,
    "MAX_TOKEN": 8192,
    "PRESENCE_PENALTY": 0.0,
}

GEMMA_INFO = {
    "API_KEY": os.environ.get("GEMMA_API_KEY", ""),
    "BASE_URL": os.environ.get("GEMMA_BASE_URL", "https://api.siliconflow.com/v1"),
    "MODEL": os.environ.get("GEMMA_MODEL", "google/gemma-4-31B-it"),
    "CHAT_MODEL": os.environ.get("GEMMA_CHAT_MODEL", "google/gemma-4-31B-it"),
    "THINK_MODEL": os.environ.get("GEMMA_THINK_MODEL", "google/gemma-4-31B-it"),
    "TEMPERATURE": 0.7,
    "TOP_P": 1.0,
    "MAX_TOKEN": 8192,
    "PRESENCE_PENALTY": 0.0,
}

LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "deepseek")
SUPPORTED_LLM_PROVIDERS = {"deepseek", "chatgpt", "gemma"}

TIANQI_INFO = {
    "IP_API_URL": os.environ.get("TIANQI_IP_API_URL", ""),
}

DATABASE_INFO = {
    "HOST": os.environ.get("DB_HOST", "127.0.0.1"),
    "PORT": os.environ.get("DB_PORT", "3306"),
    "USER": os.environ.get("DB_USER", "root"),
    "PASSWORD": os.environ.get("DB_PASSWORD", ""),
}

DETAYUN_INFO = {
    "USERNAME": os.environ.get("DETAYUN_USERNAME", ""),
    "PASSWORD": os.environ.get("DETAYUN_PASSWORD", ""),
}

MIMN_IP = {
    "IP": os.environ.get("MIMN_IP", ""),
    "PORT": os.environ.get("MIMN_PORT", ""),
}

MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "3"))
