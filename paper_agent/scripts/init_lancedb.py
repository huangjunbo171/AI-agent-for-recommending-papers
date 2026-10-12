"""初始化本机 papers/lancedb/vector_store 子库。"""

import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "paper_agent"))


def load_dotenv(path: Path) -> None:
    """读取简单 KEY=VALUE 配置，避免初始化命令强依赖 python-dotenv。"""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def main() -> int:
    """加载本地配置，初始化 LanceDB 子库并返回执行状态码。"""
    load_dotenv(PROJECT_ROOT / ".env")
    from utils.lancedb_store import LanceDBPaperStore

    store = LanceDBPaperStore()
    result = store.initialize()
    print(result)
    return 0 if result["ok"] and result["schema"]["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
