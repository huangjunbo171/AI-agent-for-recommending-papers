# AI Agent for Recommending Papers

本项目面向论文推荐场景构建社交媒体智能体。系统可以从论文库或本地论文压缩包中提取论文信息，根据账号人设筛选相关帖子，并在 X/Twitter 上完成论文阅读日记发布、关注列表互动和相关帖子推荐回复。

## arXiv 论文基础入库链路

`paper_agent/paper_agent/arxiv_ingest.py` 会按提交时间抓取 arXiv 指定分类的最新英文论文，下载 PDF 后由 MinerU 生成 `full.md`，并从中确定标题和摘要。程序会先按 Markdown 章节删除 Related Work 及其子章节，并从 References 或 Bibliography 开始截断，再把清理后的正文提交给 DeepSeek。标题、作者、分类和摘要只作为辅助元数据；程序不会退回到仅根据摘要分析。`core_method` 会生成 300～600 个英文词的详细方法说明，覆盖方法流程、关键模块、训练或推理过程、目标函数和核心创新，但不会补写正文没有的信息。

程序还会依据正文保守判断代码开放状态：明确开放为 `yes/1`，明确未开放或声明未来发布为 `no/0`，正文没有可靠说明时为 `unknown/NULL`。只有正文明确关联到本文代码的 GitHub 仓库才会写入 `code_url`，参考文献中的第三方链接不会被采用。`papers_source.source` 固定表示抓取来源 `arxiv`；`papers_info.venue` 只保存 `journal_ref` 或正文明确说明已经接收、发表的会议或期刊，`arXiv`、投稿中和审稿中均不算 venue。引用量字段目前不由这条链路更新。

主数据写入 MySQL `papers` 数据库的三张论文表，标题和摘要通过 DashScope `text-embedding-v4` 生成 1024 维向量，并同步到新 LanceDB 表 `paper_embeddings`。旧表 `paper_sections` 不会被覆盖或删除。

全文默认最多允许 240000 个字符，可通过 `PAPER_ANALYSIS_MAX_CHARS` 调整。超过上限时该论文会明确失败并跳过，不会静默截断，也不会改用摘要分析。

连接信息和密钥只通过环境变量或未纳入 Git 的 `.env` 提供：

```dotenv
DEEPSEEK_API_KEY=<your-key>
MINERU_TOKEN=<your-mineru-token>
MINERU_BASE_URL=https://mineru.net/api/v4
DASHSCOPE_API_KEY=<your-dashscope-key>
DASHSCOPE_EMBEDDING_URL=https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings
DB_HOST=<mysql-host>
DB_PORT=3306
DB_USER=<mysql-user>
DB_PASSWORD=<mysql-password>
LANCEDB_PAPERS_PATH=./papers/lancedb
```

安装独立依赖并先执行不落库验证：

```powershell
python -m pip install -r paper_agent\requirements-ingest.txt
python paper_agent\paper_agent\arxiv_ingest.py --category cs.AI --limit 1 --provider deepseek --embedding-provider dashscope --embedding-model text-embedding-v4 --mineru-model vlm --dry-run
```

确认单篇输出正常后，通过 `--paper-count`（或兼容参数 `--limit`）指定本次成功入库的论文数量。普通模式支持 1～100 篇，MinerU 会自动按每批最多 50 篇处理，重复执行会按稳定的 `paper_id` 更新记录：

```powershell
python paper_agent\paper_agent\arxiv_ingest.py --category cs.AI --paper-count 90 --provider deepseek --embedding-provider dashscope --embedding-model text-embedding-v4 --mineru-model vlm
```

如需先完成 PDF 解析、DeepSeek 全文分析和 MySQL 写入，暂不生成向量，可增加
`--skip-embedding`（或 `--analysis-only`）。该模式不会调用 DashScope，也不会写 LanceDB。

如果 MySQL 已完成、仅需修复本地向量库，可使用：

```powershell
python paper_agent\paper_agent\arxiv_ingest.py --limit 10 --embedding-provider dashscope --embedding-model text-embedding-v4 --sync-lancedb-only
```

如果需要根据 MinerU 缓存的全文重新分析 MySQL 中已有论文，可使用：

```powershell
python paper_agent\paper_agent\arxiv_ingest.py --limit 10 --provider deepseek --reanalyze-existing
```

该模式会在单个事务中更新英文关键词、详细分析、venue 和代码开放字段；不会修改论文标题、作者、摘要、引用量、`papers_source` 或 LanceDB。若全文缓存缺失、论文不是英文或本批数量不足，整批不会写入。

MySQL 是权威数据源。程序结束前会校验本次论文在三张 MySQL 表和 LanceDB 中的 ID 是否一致；任一环节不足指定数量或向量维度不是 1024 时返回失败。

如果需要显式使用 D 盘缓存的本地 BGE-M3，可传入 `--embedding-provider bge --embedding-model BAAI/bge-m3`，并通过 `EMBEDDING_MODEL_PATH` 指向已有模型。

## LanceDB 精简论文向量库接口

项目提供 `paper_agent/utils/lancedb_store.py` 数据访问层，用于管理 `papers` 目录下的 LanceDB 子库。除连接、健康检查和 Schema 校验外，它还支持安全升级空表、按 `paper_id` 幂等写入论文向量，以及读取已有论文 ID 用于跨库校验。

先安装可选依赖，并将环境变量指向服务器上 `papers` 文件目录的本地挂载点：

```powershell
pip install lancedb pyarrow
$env:LANCEDB_PAPERS_PATH = ".\papers\lancedb"
python paper_agent\scripts\init_lancedb.py
```

```python
from utils.lancedb_store import LanceDBPaperStore

store = LanceDBPaperStore(database_name="vector_store")
print(store.health_check())
store.ensure_schema()  # 仅在旧表为空时允许升级 Schema
print(store.validate_schema())
```

标准表 `paper_embeddings` 使用以下六个字段：

| **字段名** | **含义** | **备注** |
| --- | --- | --- |
| `paper_id` | 论文唯一 ID，与 MySQL 中的 ID 一致 | |
| `title` | 论文标题 | 优先使用 MinerU 从全文提取的标题 |
| `abstract` | 论文摘要 | 优先使用 MinerU 从全文提取的摘要 |
| `embedding_text` | 用于生成向量的文本 | 格式为 `Title: ...\nAbstract: ...` |
| `embedding_model` | 向量模型名称 | |
| `vector` | 论文向量 | |

子库名不允许包含绝对路径、目录分隔符或 `..`，以确保接口不能访问 `papers` 根目录之外的位置。

默认 `.env` 已设置为 `./papers/lancedb`。远端 MySQL `papers` 数据库仍是论文主数据源，入库命令通过 `paper_id` 将摘要级文本和向量同步到本机 LanceDB。MinerU 的 PDF、结果 ZIP 和 `full.md` 缓存在 `papers/mineru_cache`，该目录已被 Git 忽略。

## 2026.8.19：从被动回复到主动论文运营

早期流程主要依赖“看到帖子后立即生成一条回复”。这种方式虽然能够完成互动，却容易出现两个问题：一是回复停留在一般性讨论，没有真正把论文推荐给读者；二是所有帖子使用相近的推荐句式，论文与原帖之间的关系表达得不够准确。

本次更新没有重写 `paper_agent` 的主体模型框架，而是在现有动作判断、相关性判断和反思改写流程之外，补充了主动发帖编排、推荐策略判断、专用中文 prompt 与运行稳定性处理。核心目标是让机器人不只是“回复帖子”，而是能够先形成自己的论文阅读记录，再根据不同语境选择合适的论文推荐方式。

## Twitter 论文推荐流程如何变化

串行入口 `twitter_agent_serial.py --paper-mode` 使用帖子驱动的推荐流程：

1. 沿用现有论文候选与人设，尝试发布一次论文阅读日记；日记失败不会阻塞后续互动。
2. 从 `twitter_object_persons.txt` 每行的“主页链接, 姓名”定位账号，每个运营账号每轮随机抽取3～5个不同账号；名单不足时取全部，不补抽。
3. 实时访问这些账号主页，每人最多获取3条最近7天内的本人帖子；跳过置顶帖、纯转帖和时间不明的内容。引用帖使用外层作者的发布时间。
4. 针对每条帖子结合人设选择策略，需要论文时独立执行RAG；互动推荐的论文不受阅读日记选题限制。此模式不再按论文关键词搜索其他帖子，也不读取话题池。
5. 每个账号总互动目标随机为10～15次，保留现有动作上限与间隔；仅本次成功执行的互动计数，可用帖子不足时不强行凑够目标。

账号最新有效帖子超过30天且本次抓取明确成功时，才从TXT删除该账号；先保存带时间戳的备份，再原子替换名单，保留其他行。最近7～30天无新帖时只跳过；空结果、访问异常、置顶旧帖、纯转帖及时间不明均不作为删除依据。

真实账号名单、名单备份和浏览器指纹配置只保存在本地，不提交到仓库。首次使用时，将 `twitter_object_persons.example.txt` 复制为 `twitter_object_persons.txt`，按注释格式填入账号；也可通过 `TWITTER_OBJECT_PERSONS_PATH` 指向已有名单。名单不存在或为空时，本轮不会执行名单互动。

默认屏蔽马斯克、特朗普的中英文名称和账号别名；过滤账号身份及帖子正文、可见引用内容。可通过 `TWITTER_SENSITIVE_PERSONS_PATH` 指定UTF-8 JSON文件追加名单，例如 `{"handles":["another_handle"],"names":["Another Name"]}`。内置黑名单不会被扩展配置覆盖。

论文阅读日记采用第一人称研究笔记风格，只提炼一个值得记录的方法、发现、局限或问题。它与广告式论文摘要的区别在于：内容重点不是罗列贡献，而是说明“读完这篇论文后，账号产生了什么具体观察”。程序会在正文生成后统一补充论文引用和链接，并在有可用图片时携带论文配图。

账号执行顺序由 `paper_agent/twitter_agent/twitter_agent_serial.py` 编排；名单维护、时间与人物过滤位于 `paper_agent/utils/twitter_targets.py`；帖子驱动的RAG服务位于 `paper_agent/utils/paper_recommender.py`。所有新增策略、筛选、生成、反思改写prompt以及论文日记prompt统一维护在 `paper_agent/paper_agent/prompts_test.py`。独立PaperAgent入口及其他模式保留兼容行为。

## 评论不再使用单一推荐句式

串行论文模式先根据原帖、人设和领域选择以下四种策略；明显不适合参与的帖子直接跳过：

- **直接推荐**：简短承接原帖，提供相关论文及最匹配的信息点。
- **互动+推荐**：先补充观点、提出具体问题或比较方法，再自然引出相关论文。
- **推荐相关领域论文**：从原帖讨论的科研方向出发，选择提供具体研究线索的论文。
- **只互动**：执行点赞或结合人设的评论，不推荐论文，不调用embedding、LanceDB或论文MySQL。

前三种策略执行：**帖子文本 → embedding → LanceDB Top 5 → MySQL论文详情 → DeepSeek结合人设筛选1～3篇及信息点 → 生成与反思改写**。默认优先一篇，多篇必须提供互补信息。推荐动作只使用评论或带评论转发；策略无法识别时降级为只互动。

检索复用入库的1024维向量模型，默认DashScope `text-embedding-v4`，按余弦距离排序并只召回相同 `embedding_model` 的论文。MySQL是信息权威来源，读取方法、贡献、结果、局限等已有分析；模型只能选择召回论文ID及已有信息点编号，程序校验后才生成回复。无合适论文、详情缺失或检索筛选失败时降级为只互动；内容生成失败则跳过。

正文使用 `[1]` 等编号对应选中的论文，链接由程序追加。包含链接的完整回复最多270字符；超长时按优先级减少末位论文并重新生成，避免链接与正文错配。

可配置环境变量如下：

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `TWITTER_OBJECT_PERSONS_PATH` | 项目根目录下的 `twitter_object_persons.txt` | 大V名单 |
| `TWITTER_RAG_TOP_K` | `5` | 每条帖子召回的论文候选数，正整数 |
| `TWITTER_RAG_MAX_PAPERS` | `3` | 单条回复的论文篇数上限，1～3 |
| `TWITTER_RAG_EMBEDDING_PROVIDER` | `dashscope` | 可选 `dashscope` 或 `bge`，须与库中模型一致 |
| `TWITTER_RAG_EMBEDDING_MODEL` | 对应provider的默认模型 | 精确匹配LanceDB中的模型名称 |
| `TWITTER_SENSITIVE_PERSONS_PATH` | 未设置 | 追加敏感人物的JSON文件 |

新RAG链路显式调用DeepSeek，使用 `DEEPSEEK_*` 配置；阅读日记和其他模式仍遵循原有 `--llm-provider`。运行前须准备已入库的 `paper_embeddings` 表、MySQL三张论文表及相应服务密钥；推荐只读论文数据，不重建或迁移表。

## 运行稳定性与节奏控制

社交媒体操作如果连续发生，既不符合正常用户行为，也可能降低页面加载和素材抓取的稳定性。串行流程现在会在搜索与发帖阶段加入随机异步等待：

- 每次搜索大 V 帖子或论文相关帖子前随机等待 `3～5` 秒，搜索阶段完成后等待 `5～12` 秒。
- 发布论文日记、新闻帖或话题帖前等待 `10～25` 秒，发布完成后等待 `20～45` 秒。
- 多次帖子互动之间继续保留随机间隔，避免连续执行点赞、评论和转发。

所有新增阶段等待都可通过 `TWITTER_SLEEP_SCALE` 等比例调整。例如，设置为 `0.5` 会把等待时间缩短为原来的一半；设置为 `0` 可在本地调试时关闭这些新增等待。正式运行时建议保持默认值 `1`。

模型调用使用通用生成函数，不再调用旧的 `/post` 与 `/comment` 内部接口。新RAG互动固定使用DeepSeek；其余生成流程读取 `--llm-provider` 和对应环境变量。

模型返回字典文本时，解析流程会依次尝试标准 JSON、Python 字面量和指定字段恢复，并兼容中文引号与代码块。过去类似 `{"summary": 对某内容感兴趣，尤其关注……}` 的输出会因中文逗号和未加引号值而失败；现在系统能够尽量恢复 `summary` 等必要字段，并且不再直接使用 `eval` 解析这类模型输出。

此外，本次更新还补充了几项运行保护：大 V 人物文件缺失时跳过该阶段，普通模式仍可回退到关注列表抓取；上传论文图片前将文件路径规范化为绝对路径；未安装 `colorlog` 时使用标准日志输出，避免可选依赖阻塞主流程。

## 如何运行更新后的串行流程

下面的命令会让账号 `1` 和 `224` 立即各运行一轮论文模式。该命令会登录真实账号，并可能实际发帖、点赞、评论或转发，运行前应先确认账号、Cookie、论文目录和模型配置正确。

```powershell
python paper_agent\twitter_agent\twitter_agent_serial.py `
  --account-ids 1,224 `
  --paper-mode `
  --force-run-now `
  --llm-provider deepseek `
  --max-cycles 1
```

如果论文不在默认目录，可以显式指定研究领域和本地论文目录：

```powershell
python paper_agent\twitter_agent\twitter_agent_serial.py `
  --account-ids 1,224 `
  --paper-mode `
  --force-run-now `
  --domain "Large Language Models for Recommendation" `
  --paper-path ".\papers\zip_folder" `
  --llm-provider deepseek `
  --max-cycles 1
```

调试等待节奏时，可以先在当前 PowerShell 会话中设置缩放系数：

```powershell
$env:TWITTER_SLEEP_SCALE = "0.5"
```

常用参数包括 `--account-ids`、`--paper-mode`、`--domain`、`--paper-path`、`--force-run-now`、`--max-cycles` 和 `--max-runtime-minutes`。`--followings` 默认启用；若明确不需要关注列表素材，可以使用 `--no-followings`。模型密钥建议通过对应环境变量提供，例如 `DEEPSEEK_API_KEY` 或 `CHATGPT_API_KEY`，不要写入代码或提交到版本库。

## 历史更新

### 2026.8.19

整理并强化 Twitter 串行运营的行为节奏。在论文阅读日记、新闻帖和话题帖发布前后，以及新闻、相关帖子和关注列表帖子搜索前后，加入可记录日志的随机异步等待。新增 `TWITTER_SLEEP_SCALE`，允许按比例调整等待时间，便于在正式运营与本地调试之间切换。

将四种论文推荐回复方式拆分为独立中文 prompt，统一放入 `paper_agent/paper_agent/prompts_test.py`。业务层仍通过同一个 prompt 分发入口调用，因此没有改变 `paper_agent` 的主体流程。同步补充项目文档，说明更新后的执行顺序、策略选择、容错逻辑、运行参数与安全注意事项。

### 2026.7.24

在论文推荐回复之前加入独立的策略判断步骤。策略 agent 会根据原帖、论文标题和摘要，在“直接推荐”“互动+推荐”“同领域论文推荐”和“问题解决型推荐”之间选择一种表达方式。策略判断采用受限纯文本输出而非 JSON，降低模型输出中文标点或非标准结构时的解析风险。

调整同领域推荐语义：即使原帖讨论范围较宽，也只推荐当前目标论文，不再额外查询或生成同领域论文列表。策略生成后仍会经过原有反思改写、长度控制和链接追加，避免新策略绕过既有质量检查。

补充评论日志：日志会记录直接互动或具体论文推荐策略、原始动作、最终动作和目标论文。直接互动仍可选择点赞；需要生成文本时统一使用评论，不再转发原帖。

同时修复串行流程仍调用旧 `/post`、`/comment` 服务的问题。评论与普通发帖改为使用通用模型生成入口，遵循 `--llm-provider` 及其环境变量配置，避免局部请求继续连接旧的内部地址并产生超时。媒体上传前增加路径规范化，提升论文配图上传的稳定性。

### 2026.7.23

新增“论文阅读日记”式主动发帖能力，并将中文 prompt 移入 `prompts_test.py` 集中维护。论文日记强调第一人称阅读记录和单一研究观察，不再生成广告式摘要；正文生成后由程序补充论文引用、链接和可用配图。

调整每个账号的运营顺序：先发布一次论文阅读日记，再从 `twitter_object_persons.txt` 的大 V 主页抓取并筛选近期帖子，最后搜索论文关键词并继续复用同一套相关性判断与动作分发逻辑。多账号运行改为串行执行，减少浏览器会话和账号操作相互干扰。

### 2026.7.22

增强模型结构化输出的容错解析。对于兴趣判断、摘要筛选和活跃时间预测结果，依次尝试标准 JSON、Python 字面量及必要字段恢复，并兼容代码块、中文引号、未加引号的中文文本等常见模型输出。由此替代这些路径中的直接 `eval`，修复中文逗号导致的解析失败。

关注目标配置文件不存在时，不再直接中断抓取，而是回退到账号关注列表；日志模块在缺少可选依赖 `colorlog` 时也会使用标准输出格式继续运行。

### 2026.7.17

调整帖子筛选 prompt，只阅读中文和英文帖子，减少无法稳定理解的其他语种内容进入后续推荐流程。

### 2026.5.13

重构浏览器启动逻辑，统一 Chrome options 的生成方式，补充 profile 目录、浏览器指纹、Selenium Manager 回退以及通过 CDP 隐藏 `webdriver` 标记等配置，为账号隔离和登录稳定性提供基础。新增 `twitter_agent/cookie_login_patch.py`，并在 `paper_agent` 与 Twitter 主流程中接入，仅通过 Cookie 或 `auth_token`、`ct0` 登录；登录后会校验主页和个人页状态，并回写 Cookie、账号 URL 与最近登录时间。

`paper_agent` 同时加入论文库不可用时的本地 ZIP 回退流程，可从 `papers/zip_folder` 解压并解析 Markdown，提取标题、摘要、作者、配图和 arXiv 链接，在缺少关键词时调用模型补全。调度侧增加 `FORCE_RUN_NOW=1` 立即执行开关，并移除运行中的调试断点。模型调用补充统一重试与思考、非思考模式封装，DeepSeek 配置支持通过环境变量覆盖。此外，新增 `generate_2fa_code.py`，用于在本地生成 2FA 验证码。

### 2026.5.10

完成本地 MySQL 数据库接入与运行排查。数据库默认连接本地实例，并支持通过 `DB_HOST`、`DB_PORT`、`DB_USER`、`DB_PASSWORD` 环境变量覆盖。调整 `paper_agent` 的导入方式，避免 Twitter 主流程被小红书或微博相关依赖阻塞；将 `AccountPortrait` 改为按需导入，并在缺少 `sentence-transformers` 或本地 embedding 模型路径不存在时给出更明确的错误提示。同时更新了带有浏览器指纹配置能力的 `base_bot`。
