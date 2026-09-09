# Personal News Agent

基于 FastAPI、PostgreSQL、Redis 和 DeepSeek 的个人智能新闻 Agent。系统目标是持续采集多领域新闻，完成清洗、去重、事件聚类、分类、排序和摘要，并在 `Asia/Singapore` 时区每天 09:00 生成日报，通过可插拔渠道发送。

当前仓库已完成 **Phase 4：多级新闻去重与事件聚类**。Phase 4 在前三阶段基础上增加 `NewsDedupService`、`NewsClusteringService`：按 URL hash、规范化标题、可配置标题相似度和可选 Embedding 四层信号识别重复报道，并通过现有 `event_news` 关联对象保留每一条文章及其来源。DeepSeek、Agent、日报和微信适配器仍按路线图留待后续阶段。

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
6. DeepSeek 统一客户端与结构化输出
7. News Agent 与工具调用
8. 每日日报流水线
9. 微信适配器
10. Docker 生产化
11. 完整测试
12. 监控、限流与性能优化

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

