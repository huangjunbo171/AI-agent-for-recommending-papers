# AI-agent-for-recommending-papers
有关论文推荐的 AI 智能体

2026.5.10
完成本地 MySQL 数据库接入与运行排查。将数据库配置改为默认连接本地，并支持通过 `DB_HOST`、`DB_PORT`、`DB_USER`、`DB_PASSWORD` 环境变量覆盖；将默认数据库密码更新为本地使用的。同时调整了 `paper_agent` 的导入方式，避免在运行 Twitter 主流程时被 `xhs/weibo` 相关依赖阻塞；将 `AccountPortrait` 改为按需导入，并为 `sentence-transformers` 缺失或本地 embedding 模型路径不存在时提供更明确的报错提示。更新了带有指纹配置能力的 `base_bot`。

2026.5.13
首先，重构了浏览器启动逻辑，统一了 Chrome options 的生成方式，补充了 profile 目录、浏览器指纹、Selenium Manager 回退以及 CDP 隐藏 `webdriver` 标记等配置，为账号隔离和登录稳定性打了基础。其次，新增 `twitter_agent/cookie_login_patch.py`，并在 `paper_agent` 与 `twitter_main` 中接入，仅通过 `Cookie` 或 `auth_token`/`ct0` 进行 Twitter 登录，登录后会自动校验主页和个人页状态，刷新并回写 cookie、账号 URL 与最近登录时间。

同时，`paper_agent` 增加了论文库不可用时的本地 ZIP 回退流程：可直接从 `papers/zip_folder` 解压并解析 markdown，提取标题、摘要、作者、配图和 arXiv 链接，在缺少关键词时再调用模型补全，保证宣传主流程不断。调度侧也增加了 `FORCE_RUN_NOW=1` 的立即执行开关，并移除了运行中的调试断点，方便本地排查。模型调用部分则把通用文本生成逻辑收敛到 DeepSeek 接口，补上统一重试与思考/非思考模式封装，`DEEPSEEK_API_KEY` 也支持通过环境变量覆盖。除此之外，还补充了 `generate_2fa_code.py` 这样的 2FA 辅助脚本，支持在本地生成2FAcode验证码。
