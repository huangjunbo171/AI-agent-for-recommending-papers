from utils.utils import timer, split_think_and_answer
import requests
import time
import os
import base64
import json
import asyncio
from urllib.parse import urlparse
from config import CHATGPT_INFO, DEEPSEEK_INFO, GEMMA_INFO, LLM_PROVIDER, MAX_RETRIES, SUPPORTED_LLM_PROVIDERS


def _normalize_provider(provider=None):
    default_provider = os.environ.get("LLM_PROVIDER", LLM_PROVIDER)
    active_provider = (provider or default_provider or "deepseek").strip().lower()
    if active_provider == "openai":
        active_provider = "chatgpt"
    if active_provider == "siliconflow":
        active_provider = "gemma"
    if active_provider not in SUPPORTED_LLM_PROVIDERS:
        print(f"Unsupported LLM provider: {active_provider}, fallback to deepseek")
        return "deepseek"
    return active_provider


def _env_or_default(name, default, caster=None):
    value = os.environ.get(name)
    if value in (None, ""):
        return default
    if caster is None:
        return value
    try:
        return caster(value)
    except Exception:
        return default


def _provider_config(provider):
    active_provider = _normalize_provider(provider)
    if active_provider == "chatgpt":
        return {
            "API_KEY": _env_or_default("CHATGPT_API_KEY", CHATGPT_INFO.get("API_KEY", "")),
            "BASE_URL": _env_or_default("CHATGPT_BASE_URL", CHATGPT_INFO.get("BASE_URL", "https://api.openai.com/v1")),
            "MODEL": _env_or_default("CHATGPT_MODEL", CHATGPT_INFO.get("MODEL", "gpt-4.1")),
            "CHAT_MODEL": _env_or_default("CHATGPT_CHAT_MODEL", CHATGPT_INFO.get("CHAT_MODEL", "gpt-4.1-mini")),
            "THINK_MODEL": _env_or_default("CHATGPT_THINK_MODEL", CHATGPT_INFO.get("THINK_MODEL", "gpt-4.1")),
            "TEMPERATURE": _env_or_default("CHATGPT_TEMPERATURE", CHATGPT_INFO.get("TEMPERATURE", 1.0), float),
            "TOP_P": _env_or_default("CHATGPT_TOP_P", CHATGPT_INFO.get("TOP_P", 1.0), float),
            "MAX_TOKEN": _env_or_default("CHATGPT_MAX_TOKEN", CHATGPT_INFO.get("MAX_TOKEN", 8192), int),
            "PRESENCE_PENALTY": _env_or_default("CHATGPT_PRESENCE_PENALTY", CHATGPT_INFO.get("PRESENCE_PENALTY", 0.0), float),
        }
    if active_provider == "gemma":
        return {
            "API_KEY": _env_or_default("GEMMA_API_KEY", GEMMA_INFO.get("API_KEY", "")),
            "BASE_URL": _env_or_default("GEMMA_BASE_URL", GEMMA_INFO.get("BASE_URL", "https://api.siliconflow.com/v1")),
            "MODEL": _env_or_default("GEMMA_MODEL", GEMMA_INFO.get("MODEL", "google/gemma-4-31B-it")),
            "CHAT_MODEL": _env_or_default("GEMMA_CHAT_MODEL", GEMMA_INFO.get("CHAT_MODEL", "google/gemma-4-31B-it")),
            "THINK_MODEL": _env_or_default("GEMMA_THINK_MODEL", GEMMA_INFO.get("THINK_MODEL", "google/gemma-4-31B-it")),
            "TEMPERATURE": _env_or_default("GEMMA_TEMPERATURE", GEMMA_INFO.get("TEMPERATURE", 0.7), float),
            "TOP_P": _env_or_default("GEMMA_TOP_P", GEMMA_INFO.get("TOP_P", 1.0), float),
            "MAX_TOKEN": _env_or_default("GEMMA_MAX_TOKEN", GEMMA_INFO.get("MAX_TOKEN", 8192), int),
            "PRESENCE_PENALTY": _env_or_default("GEMMA_PRESENCE_PENALTY", GEMMA_INFO.get("PRESENCE_PENALTY", 0.0), float),
        }
    return {
        "API_KEY": _env_or_default("DEEPSEEK_API_KEY", DEEPSEEK_INFO.get("API_KEY", "")),
        "BASE_URL": _env_or_default("DEEPSEEK_BASE_URL", DEEPSEEK_INFO.get("BASE_URL", "https://api.deepseek.com")),
        "MODEL": _env_or_default("DEEPSEEK_MODEL", DEEPSEEK_INFO.get("MODEL", "deepseek-reasoner")),
        "CHAT_MODEL": _env_or_default("DEEPSEEK_CHAT_MODEL", DEEPSEEK_INFO.get("CHAT_MODEL", "deepseek-chat")),
        "THINK_MODEL": _env_or_default("DEEPSEEK_THINK_MODEL", DEEPSEEK_INFO.get("THINK_MODEL", "deepseek-reasoner")),
        "TEMPERATURE": _env_or_default("DEEPSEEK_TEMPERATURE", DEEPSEEK_INFO.get("TEMPERATURE", 1.0), float),
        "TOP_P": _env_or_default("DEEPSEEK_TOP_P", DEEPSEEK_INFO.get("TOP_P", 1.0), float),
        "MAX_TOKEN": _env_or_default("DEEPSEEK_MAX_TOKEN", DEEPSEEK_INFO.get("MAX_TOKEN", 8192), int),
        "PRESENCE_PENALTY": _env_or_default("DEEPSEEK_PRESENCE_PENALTY", DEEPSEEK_INFO.get("PRESENCE_PENALTY", 0.0), float),
    }


def describe_active_provider(provider=None):
    active_provider = _normalize_provider(provider)
    config = _provider_config(active_provider)
    api_key = config.get("API_KEY") or ""
    if api_key:
        masked_key = f"{api_key[:6]}...{api_key[-4:]}" if len(api_key) > 10 else "***"
    else:
        masked_key = "<empty>"
    return {
        "provider": active_provider,
        "base_url": config.get("BASE_URL"),
        "model": config.get("MODEL"),
        "chat_model": config.get("CHAT_MODEL"),
        "think_model": config.get("THINK_MODEL"),
        "api_key": masked_key,
    }


def _provider_headers(provider):
    config = _provider_config(provider)
    return {
        "Authorization": f"Bearer {config['API_KEY']}",
        "Content-Type": "application/json",
    }


def _provider_url(provider):
    config = _provider_config(provider)
    return f"{config['BASE_URL'].rstrip('/')}/chat/completions"


def _should_bypass_proxy(provider):
    active_provider = _normalize_provider(provider)
    if active_provider == "gemma":
        return True
    base_url = _provider_config(active_provider).get("BASE_URL", "")
    host = urlparse(base_url).netloc.lower()
    return "api.siliconflow.com" in host


def _ensure_no_proxy_for_siliconflow():
    bypass_hosts = "api.siliconflow.com"
    for env_name in ("NO_PROXY", "no_proxy"):
        current = os.environ.get(env_name, "")
        parts = [item.strip() for item in current.split(",") if item.strip()]
        if bypass_hosts not in parts:
            parts.append(bypass_hosts)
        os.environ[env_name] = ",".join(parts)


def _provider_timeout(active_provider, purpose="chat"):
    if active_provider == "gemma":
        return 150 if purpose == "chat" else 210
    if active_provider == "deepseek":
        return 60 if purpose == "chat" else 120
    return 60 if purpose == "chat" else 90


def _message_text(message_value):
    if isinstance(message_value, str):
        return message_value
    if isinstance(message_value, list):
        parts = []
        for item in message_value:
            if isinstance(item, str):
                parts.append(item)
                continue
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text" and item.get("text"):
                parts.append(item["text"])
                continue
            text_info = item.get("text")
            if isinstance(text_info, dict) and text_info.get("value"):
                parts.append(text_info["value"])
        return "".join(parts)
    return ""


async def _chat_completion(prompt, provider, model, timeout=60, retries=MAX_RETRIES):
    active_provider = _normalize_provider(provider)
    config = _provider_config(active_provider)
    if not config.get("API_KEY"):
        print(f"Call {active_provider} skipped: empty API key")
        return None
    data = {
        "model": model,
        "messages": prompt,
        "temperature": config["TEMPERATURE"],
        "top_p": config["TOP_P"],
        "max_tokens": config["MAX_TOKEN"],
        "presence_penalty": config["PRESENCE_PENALTY"],
        "stream": False,
    }

    for attempt in range(retries):
        try:
            if _should_bypass_proxy(active_provider):
                _ensure_no_proxy_for_siliconflow()
            request_kwargs = {
                "url": _provider_url(active_provider),
                "headers": _provider_headers(active_provider),
                "json": data,
                "timeout": timeout,
            }
            if _should_bypass_proxy(active_provider):
                session = requests.Session()
                session.trust_env = False
                response = session.post(**request_kwargs)
            else:
                response = requests.post(**request_kwargs)
            if response.status_code in (401, 403):
                provider_info = describe_active_provider(active_provider)
                print(
                    f"Call {active_provider} auth failed: "
                    f"base_url={provider_info['base_url']}, "
                    f"model={model}, api_key={provider_info['api_key']}"
                )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]
        except Exception as e:
            print(f"Call {active_provider} failed (attempt {attempt + 1}): {e}")
            if attempt < retries - 1:
                await asyncio.sleep(3 * (attempt + 1))
            else:
                return None


def _extract_answer_and_think(message):
    if not message:
        return None, None

    answer = _message_text(message.get("content", ""))
    think = _message_text(message.get("reasoning_content", ""))

    if not think and answer:
        split_think, split_answer = split_think_and_answer(answer)
        if split_think or split_answer:
            think = split_think
            answer = split_answer or answer

    return think, answer


@timer
async def content_generation(prompt):
    url = "http://region-3.seetacloud.com:47826/general"
    payload = {"messages": prompt}
    response = requests.post(url, json=payload).json()
    return response["response"][0]


async def general_generation(prompt, provider=None, model=None):
    active_provider = _normalize_provider(provider)
    config = _provider_config(active_provider)
    message = await _chat_completion(
        prompt,
        provider=active_provider,
        model=model or config["CHAT_MODEL"],
        timeout=_provider_timeout(active_provider, purpose="chat"),
        retries=MAX_RETRIES,
    )
    if not message:
        return None
    return _message_text(message.get("content"))


async def general_generation_think(prompt, provider=None, model=None):
    active_provider = _normalize_provider(provider)
    config = _provider_config(active_provider)
    timeout = _provider_timeout(active_provider, purpose="think")
    message = await _chat_completion(
        prompt,
        provider=active_provider,
        model=model or config["THINK_MODEL"],
        timeout=timeout,
        retries=MAX_RETRIES,
    )
    return _extract_answer_and_think(message)


async def general_generation_deepseek(prompt, provider=None, model=None):
    active_provider = _normalize_provider(provider)
    config = _provider_config(active_provider)
    message = await _chat_completion(
        prompt,
        provider=active_provider,
        model=model or config["MODEL"],
        timeout=_provider_timeout(active_provider, purpose="chat"),
        retries=MAX_RETRIES,
    )
    if not message:
        return None
    return _message_text(message.get("content"))


async def generation_post(text, model, language="涓枃绠€浣?", output_len=1000, character=None, style="formal"):
    data = {
        "input": text,
        "model": model,
        "language": language,
        "description": character,
        "output_len": output_len,
        "style": style,
    }
    api = "http://172.16.32.11:30103/post"
    start = time.time()
    response = requests.post(api, json=data).json()
    end = time.time()
    response_time = end - start
    return response, response_time


async def generation_comment(text, model, language="涓枃绠€浣?", output_len=1000, character=None, style="formal"):
    data = {
        "input": text,
        "model": model,
        "language": language,
        "description": character,
        "style": style,
        "output_len": output_len,
    }
    api = "http://172.16.32.11:30103/comment"
    start = time.time()
    response = requests.post(api, json=data).json()
    end = time.time()
    response_time = end - start
    return response, response_time


async def picture_generation(prompt):
    ark_api_key = "94abcc98-9ec1-4340-8217-5cf14264732f"
    url = "https://ark.cn-beijing.volces.com/api/v3/images/generations"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {ark_api_key}",
    }
    data = {
        "model": "doubao-seedream-3-0-t2i-250415",
        "prompt": prompt,
        "response_format": "b64_json",
        "size": "1024x1024",
        "seed": 12,
        "guidance_scale": 2.5,
        "watermark": False,
    }

    response = requests.post(url, headers=headers, data=json.dumps(data))
    if response.status_code == 200:
        images = response.json()["data"]
    else:
        print(f"Request failed, status: {response.status_code}, error: {response.text}")
        images = None

    if not images:
        return []

    current_time = time.strftime("%Y-%m-%d-%H-%M-%S", time.localtime())
    abs_path = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
    save_dir = os.path.join(abs_path, f"images\\{current_time}")
    if not os.path.exists(save_dir):
        os.makedirs(save_dir)

    image_paths = []
    for i, image in enumerate(images):
        image_data = base64.b64decode(image["b64_json"])
        save_path = os.path.join(save_dir, f"image_{i}.png")
        with open(save_path, "wb") as f:
            f.write(image_data)
        image_paths.append(save_path)
    return image_paths


if __name__ == "__main__":
    async def main():
        print(await generation_post(text="support kamala harris", model="Qwen-72b-Instruct", language="鑻辨枃"))

    asyncio.run(main())
