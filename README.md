# AI Agent for Recommending Papers

当研究者在 X 上讨论某个方法或实验结果时，这个项目尝试找到相关论文，并说明论文里哪一点能回应原帖。程序也可以发布论文阅读日记。

## 代码概览

**论文入库。** 从 arXiv 获取论文，使用 MinerU 解析 PDF，由 DeepSeek 分析正文。MySQL 保存论文详情，LanceDB 保存标题和摘要的向量。[入库入口](paper_agent/paper_agent/arxiv_ingest.py)

**阅读日记。** 程序依次登录指定账号，根据账号关注的研究方向选题，尝试发布附论文链接的阅读日记。[串行入口](paper_agent/twitter_agent/twitter_agent_serial.py)

**帖子互动。** 程序从目标名单获取近期帖子，结合原帖和账号人设选择互动方式。需要推荐论文时，先通过 LanceDB 召回，再从 MySQL 读取论文详情并生成回复。[目标筛选](paper_agent/utils/twitter_targets.py) · [论文推荐](paper_agent/utils/paper_recommender.py)

## 运行说明

准备 Python 依赖和 Chrome。按配置示例设置 MySQL 连接和模型密钥，按需填写代理。账号库需要有有效 Cookie，推荐流程需要论文数据和 LanceDB 索引。[配置示例](paper_agent/config.example.py)

在仓库根目录准备 `twitter_object_persons.txt`。当前分支的阅读日记从 `papers/zip_folder/` 中的 ZIP 选题，也可用 `--paper-path` 指定 ZIP 文件或已解压的目录。[目标名单示例](twitter_object_persons.example.txt)

在仓库根目录用 PowerShell 执行。命令会让每个指定账号立即运行一轮，期间可能在 X 上发帖或互动。

```powershell
if (-not (Test-Path .\paper_agent\config.py)) {
    Copy-Item .\paper_agent\config.example.py .\paper_agent\config.py
}
$env:PYTHONPATH = (Get-Location).Path
$accountIds = (Read-Host '输入账号 ID，多个用逗号分隔').Trim()
if ($accountIds -notmatch '^\d+(,\d+)*$') { throw '账号 ID 格式无效' }
python .\paper_agent\twitter_agent\twitter_agent_serial.py --account-ids $accountIds --paper-mode --force-run-now --llm-provider deepseek --max-cycles 1
```

运行日志位于 `logs/twitter/`。可通过日志中的帖子链接核对发布结果，分享日志前请移除账号凭据。
