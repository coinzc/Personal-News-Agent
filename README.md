# Personal News Agent

基于 FastAPI、PostgreSQL、Redis 和 DeepSeek 的个人智能新闻 Agent。系统目标是持续采集多领域新闻，完成清洗、去重、事件聚类、分类、排序和摘要，并在 `Asia/Singapore` 时区每天 09:00 生成日报，通过可插拔渠道发送。

当前仓库已完成 **应用编排与 API 接线**。FastAPI lifespan 会创建运行时容器，按配置初始化 DeepSeek、Redis、微信适配器和可选 APScheduler；`/api/agent/chat`、`/api/digest/generate` 和 `/api/wechat/webhook` 已接入容器。日报服务在 `Asia/Singapore` 时区按天加载新闻，按八大领域去重并选择 Top 3，保存为 `DailyDigest`，并通过 Redis 锁和数据库唯一约束保证同一天幂等。

## 环境要求

- Python 3.12+
- Docker Engine + Docker Compose v2（部署时）
- Git

## 本地开发

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
pytest
uvicorn app.main:app --reload
```

Linux 激活虚拟环境及复制配置时分别使用 `source .venv/bin/activate` 和 `cp .env.example .env`。启动后访问 `http://localhost:8000/health` 或 `http://localhost:8000/docs`。

## Docker 部署

复制 `.env.example` 为 `.env`，填写真实密钥和生产密码后执行：

```bash
docker compose up -d --build
docker compose ps
```

Compose 会启动 backend、PostgreSQL、Redis 和 Nginx，并通过 healthcheck 控制依赖启动顺序。生产环境应替换默认数据库密码、配置防火墙/TLS，并将 `.env` 保存在服务器而不提交到 Git。

## 数据库迁移

本项目通过 Alembic 管理 PostgreSQL schema，应用默认读取 .env 中的 DATABASE_URL。

运行 alembic upgrade head 应用迁移，运行 python -m app.db.init_db 初始化数据库，运行 alembic downgrade base 回滚到空 schema。

数据库层使用 SQLAlchemy 2.x typed declarative models 和 async_sessionmaker。NewsItem.url 有数据库唯一约束；NewsEvent 与 NewsItem 通过 event_news association object 建立多对多关系。

## 目录约定

```text
app/
|-- api/             # HTTP 路由
|-- agent/           # DeepSeek Agent（后续阶段）
|-- cache/           # Redis 缓存与分布式锁（后续阶段）
|-- channels/        # 微信等消息渠道（后续阶段）
|-- collectors/      # RSS/API Collector（后续阶段）
|-- config.py        # Pydantic Settings 配置
|-- db/              # 数据库会话、Base 与迁移
|-- llm/             # DeepSeek 统一封装（后续阶段）
|-- logging_config.py
|-- models/          # SQLAlchemy ORM 模型
|-- schemas/         # Pydantic API 模型
|-- scheduler/       # APScheduler 任务（后续阶段）
|-- services/        # 业务服务（后续阶段）
|-- utils/           # 通用工具（后续阶段）
`-- main.py          # 应用工厂和入口
tests/               # 单元、集成和 API 测试
docker/              # Nginx 等部署配置
prompts/             # 版本化 Prompt 模板（后续阶段）
```

## 分阶段路线图

1. 项目初始化（已完成）
2. 数据库模型与迁移（已完成）
3. 异步新闻采集（已完成）
4. 多级去重与 NewsEvent（已完成）
5. 事件聚类（已完成）
6. DeepSeek 统一客户端与结构化输出（已完成）
7. News Agent 与工具调用（已完成）
8. 每日日报流水线（已完成）
9. 微信适配器（已完成）
10. 应用编排与 API 接线（已完成）
11. Docker 生产化
12. 完整测试
13. 监控、限流与性能优化

每个阶段都会先检查现有结构，完成实现后运行相关测试并更新本文档。
## Phase 3 Collector

`BaseCollector` 定义异步采集契约，`collect_many` 使用 `asyncio.gather(..., return_exceptions=True)` 隔离单个源的失败。`RSSCollector` 通过 `httpx.AsyncClient` 和 `feedparser` 处理 RSS/Atom，支持超时、DNS/连接错误、429/5xx 指数退避重试；其他 4xx 直接失败。解析结果会提取标题、链接、作者、发布时间、正文和图片，正文会移除脚本/样式节点，URL 会移除 fragment、默认端口和 `utm_*`/`fbclid`/`gclid` 追踪参数。

Collector 只返回 `CollectedNews`，不直接依赖业务写库。`NewsIngestionService` 将结果映射到 `NewsItem`，通过数据库 URL 唯一约束和嵌套事务跳过重复 URL，同时保留同批其他成功插入记录。

Phase 3 测试全部使用 `httpx.MockTransport`，包含 RSS、Atom、3 个 Mock Source、多源失败隔离、HTTP 4xx/5xx、DNS/连接失败、HTML 清洗、URL 标准化和重复 URL 写入场景；不访问真实新闻网站。

## Phase 4 去重与事件聚类

`NewsDedupService` 是不依赖数据库的可测试比较服务：

1. URL hash：对 scheme、host、默认端口、尾部斜杠及 `utm_*`/`fbclid`/`gclid` 参数做标准化后计算 SHA-256。
2. normalized title：Unicode NFKC、大小写、标点和常见中英文同义表达归一化；中文标题使用字符 token，英文标题使用词 token。
3. title similarity：结合 token Jaccard、顺序相似度和包含率，默认阈值 `0.78`，避免只因共享一个实体而误合并。
4. embedding similarity：通过 `EmbeddingSimilarityProvider` 注入，默认不调用外部服务；`MockEmbeddingProvider` 可用于测试。默认阈值 `0.85`。

阈值和别名均可通过 `DeduplicationConfig` 覆盖，例如 `NewsDedupService(config=DeduplicationConfig(similarity_threshold=0.82))`。当前阶段选择可解释的词法候选匹配，是因为新闻标题规模有限且无需额外 API 成本；后续接入 Embedding 后仍会保留前三级作为快速过滤和审计证据。

`NewsClusteringService` 不删除重复文章。它会复用或创建 `NewsEvent`，用 `EventNews` 保留所有报道和来源，并在重复运行时避免重复关联；`cluster_pending()` 只处理尚未关联事件的文章。

Phase 4 测试覆盖 URL 完全重复、标题轻微改写、中文/英文同一事件、无关标题、Embedding mock、多来源事件关联、待处理文章和幂等重复运行。

## Phase 5 DeepSeek LLM Service

`app/llm/client.py` 定义不绑定供应商的异步 `LLMClient` 和统一异常边界；`app/llm/deepseek.py` 使用 OpenAI-compatible `AsyncOpenAI` 连接 DeepSeek。真实客户端创建时必须提供 `DEEPSEEK_API_KEY`，密钥不会出现在日志、错误消息或测试代码中。请求默认关闭 SDK 内置 retry，由服务层统一执行指数退避（`LLM_MAX_RETRIES`、`LLM_BACKOFF_FACTOR`），并将 timeout、429、5xx/连接错误转换为可处理的领域异常。

`LLMClient.complete_structured()` 先解析 JSON，再用 Pydantic 严格 schema 校验；额外字段、缺失字段和超出范围的数值都会被拒绝。`NewsClassifier` 输出 category/subcategory/confidence/tags，`NewsSummarizer` 输出带 `source_url` 的摘要和要点，`NewsRanker` 输出五个 0-100 因素，并用固定权重计算最终 `importance_score`，避免由 LLM 单独决定排序。

Phase 5 测试完全使用 Fake SDK/注入式客户端，覆盖 JSON 模式、usage/latency、429/5xx/timeout 重试、模型拒答、非法 JSON、schema 校验和三个新闻服务，不访问真实 DeepSeek API。

## Phase 6 News Agent

Phase 6 实现真正的 Tool Calling Agent：`NewsAgent` 先加载会话历史，再把用户请求和工具 schema 交给 DeepSeek；模型返回工具调用后，由 `ToolRegistry` 验证参数并执行，结果以 `tool` 消息回传模型，直到模型生成最终回答或达到最大轮数。Agent 本身不操作数据库，只依赖 `AgentMemory` 与 `ToolRegistry` 抽象。

当前注册了 `search_news`、`get_latest_news`、`get_news_by_category`、`get_news_detail`、`search_events`、`get_daily_digest`、`analyze_news` 和 `summarize_news`。新增工具只需定义 Pydantic 参数模型并注册 `ToolSpec`，不需要修改查询意图的 `if/else` 分支。`SQLAlchemyNewsToolService` 是数据库业务适配器，工具层与 Agent 编排保持解耦。

会话通过 `InMemoryConversationMemory`（测试/本地）或 `SQLAlchemyConversationMemory`（生产）保存用户消息、助手消息、tool calls、conversation ID 和时间戳。system prompt 位于 `prompts/agent_system.txt`，通过 `app/agent/prompts.py` 加载并带版本标识。

Phase 6 测试使用 Mock DeepSeek，覆盖今日新闻、AI 分类新闻、新闻详情、历史事件查询、工具参数校验、未知工具拒绝和会话持久化，不访问真实 API 或新闻网站。

## 质量检查

```bash
ruff check app tests
mypy app
pytest --cov=app
```

## 安全基线

- 所有密钥只通过环境变量或部署平台 Secret 注入。
- `.env` 已加入 `.gitignore`；提交前检查 `git diff --staged`。
- 当前 `/health` 不连接外部服务，只反映进程存活；后续将增加独立的 readiness 检查。
- 管理接口鉴权、URL 白名单、Prompt Injection 防护和敏感日志过滤将在对应业务阶段实现。


## Phase 7 Daily News Digest

`DailyDigestService.generate_daily_digest()` 编排 Collect → Deduplicate → Cluster → Rank → Summarize → Compose 流程。默认覆盖 AI、科技、编程、财经、商业、国际、科学、游戏八个领域，每类最多输出 3 条不同事件；每条包含一句话摘要、为什么重要、来源 URL 和标准化发布时间，正文限制在可配置长度内，并附趋势分析和“今日最值得关注的 3 件事”。

服务通过注入式 collector、去重/聚类/排序/摘要/趋势步骤连接现有模块，失败会写入 `Task` 和 `DailyDigest.error_message`，不会让调度器崩溃。Redis 分布式锁 `news-agent:digest:<user>:<date>` 防止多实例重复运行，`daily_digests(user_id, digest_date)` 唯一约束提供最终幂等保护；无 Redis 的测试环境使用安全的进程内锁替身。

`app/scheduler/jobs.py` 提供 APScheduler 入口，使用显式 `Asia/Singapore` 时区在每天 09:00 触发日报任务，`max_instances=1`、`coalesce=True` 并隔离任务异常。Phase 7 测试覆盖正常生成、重复执行、新闻为空和 DeepSeek 摘要失败路径。


## Phase 8 微信适配器与日报推送

当前微信范围是个人微信接收日报和消息，不接入企业微信或公众号作为接收渠道。`app/channels/base.py` 定义 provider-neutral 的 MessageChannel，`app/channels/wechat.py` 提供 WeChatAdapter：可注入微信网关/webhook 或测试 sender，支持超时、429/5xx/网络错误指数退避，以及按 max_chars 按行分片发送。

DigestDeliveryService 负责将 DailyDigest 发送到微信 recipient；成功写入 sent_at 并将状态改为 sent，失败写入 send_failed 和错误信息。Phase 8 测试使用 httpx.MockTransport 和注入 sender，不访问真实微信服务。

## 应用编排与 API 接线

`app/runtime.py` 提供 `ApplicationContainer`，统一持有 Redis、DeepSeek 和 WeChatAdapter，并为每次 Agent/日报请求创建独立 SQLAlchemy Session。FastAPI lifespan 在启动时创建容器，在关闭时释放 LLM、Redis 和 APScheduler 资源；设置 `ENABLE_SCHEDULER=true` 后，调度器会在 `Asia/Singapore` 每天 09:00 执行生成并发送日报。

当前 API：

- `POST /api/agent/chat`：调用 Tool Calling NewsAgent。
- `POST /api/digest/generate`：手动生成指定日期日报。
- `POST /api/wechat/webhook`：接收微信网关转发的消息并交给 Agent，可用 `X-WeChat-Webhook-Token` 校验。

真实端到端运行需要填写 DeepSeek API Key、PostgreSQL/Redis 配置，并提供个人微信网关 endpoint；未配置 DeepSeek 时 Agent API 返回 503。
