# Personal News Agent

一个基于 FastAPI、PostgreSQL、Redis 和 DeepSeek 的个人新闻 Agent。

系统定时抓取 RSS 新闻，完成清洗、URL 去重、标题相似度去重、事件聚类、排序和中文摘要，并在每天 `09:00`（`Asia/Shanghai`）生成日报，通过企业微信群机器人发送。用户也可以通过 Agent API 或配置好的微信网关查询新闻、分析事件和查看历史内容。

## 功能

- 异步 RSS/Atom 采集：超时、重试、指数退避、HTML 清洗和 URL 标准化。
- 多级去重：URL、标题规范化、标题相似度，并预留 Embedding 接口。
- 事件聚类：相同事件保留多个报道和来源，不删除原始新闻。
- DeepSeek：结构化分类、中文翻译、摘要、排序和 Tool Calling。
- News Agent：搜索新闻、按领域查询、查看详情、搜索事件、分析和总结。
- 每日日报：AI、科技、编程、财经、商业、国际、科学七个展示领域，每个领域最多 3 条。
- 企业微信推送：空领域隐藏、领域表情、北京时间、原文链接集中展示、按 UTF-8 字节安全分片。
- 运行保障：PostgreSQL 持久化、Redis 日报锁、任务状态、失败重试、Docker Compose 部署。

## 系统架构

```text
RSS sources
    │
    ▼
Collectors ──> Ingestion ──> Deduplication ──> Event clustering
                                                │
                                                ▼
                                          PostgreSQL
                                                │
                  ┌─────────────────────────────┴──────────────────────────┐
                  ▼                                                        ▼
          DailyDigestService                                      News Agent + Tools
                  │                                                        │
                  └───────────────> DeepSeek / Redis / WeCom <────────────┘

FastAPI <── Nginx <── HTTP clients
APScheduler ──> RSS collection and 09:00 digest jobs
```

`app/runtime.py` 是运行时组合入口，负责创建数据库会话、Redis、DeepSeek 客户端和消息渠道。Agent 只调用工具，不直接操作 ORM；日报服务和采集服务分别负责业务编排与数据写入。

## 技术栈

| 层 | 技术 |
| --- | --- |
| API | Python 3.12、FastAPI、Pydantic |
| 数据 | PostgreSQL、SQLAlchemy 2.x、Alembic |
| 缓存与锁 | Redis |
| AI | DeepSeek OpenAI-compatible API |
| 采集 | httpx、asyncio、feedparser、BeautifulSoup |
| 调度 | APScheduler |
| 部署 | Docker Compose、Nginx |
| 测试与质量 | Pytest、Ruff、MyPy |

## 快速开始

### Docker Compose

需要 Docker Engine 和 Docker Compose v2。

```bash
git clone git@github.com:coinzc/Personal-News-Agent.git
cd Personal-News-Agent
cp .env.example .env
```

编辑 `.env`，至少配置：

```dotenv
POSTGRES_PASSWORD=replace-with-a-strong-password
DEEPSEEK_API_KEY=your-deepseek-api-key
MESSAGE_CHANNEL=wecom_group_bot
WECOM_GROUP_BOT_WEBHOOK=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=...
```

启动服务：

```bash
docker compose up -d --build
docker compose ps
```

初始化数据库和默认 RSS 源：

```bash
docker compose exec backend python -m app.db.init_db
docker compose exec backend python -m app.db.seed_sources
```

访问：

- API 文档：`http://SERVER_IP/docs`
- 健康检查：`http://SERVER_IP/health`

### Ubuntu 一键部署

`scripts/deploy.sh` 支持 Ubuntu 22.04/24.04，会安装 Docker（如果缺少）、创建 `.env`、生成数据库密码、执行迁移、初始化 RSS 源并检查健康状态。

```bash
sudo bash scripts/deploy.sh
```

没有外部密钥时可以先启动基础服务：

```bash
sudo bash scripts/deploy.sh --allow-incomplete
```

脚本会保留已有 `.env` 和 Docker 数据卷。查看日志：

```bash
docker compose logs -f --tail=200 backend
```

生产环境建议只开放 `80/443` 和 SSH，不直接暴露 PostgreSQL `5432`、Redis `6379`。HTTPS、UFW、备份和升级见 [UBUNTU_DEPLOYMENT.md](UBUNTU_DEPLOYMENT.md)。

## 配置

所有配置来自 `.env`，模板见 [.env.example](.env.example)。

| 变量 | 作用 | 默认值 |
| --- | --- | --- |
| `DATABASE_URL` | PostgreSQL 连接串 | Compose 中为 `postgres` 服务 |
| `REDIS_URL` | Redis 连接串 | Compose 中为 `redis` 服务 |
| `DEEPSEEK_API_KEY` | DeepSeek 密钥 | 空 |
| `DEEPSEEK_MODEL` | 使用的模型 | `deepseek-chat` |
| `TIMEZONE` | 采集和日报时区 | `Asia/Shanghai` |
| `ENABLE_SCHEDULER` | 是否启用定时任务 | `false` |
| `NEWS_COLLECTION_INTERVAL_MINUTES` | RSS 采集间隔 | `30` |
| `MESSAGE_CHANNEL` | 消息渠道 | `wechat` |
| `WECOM_GROUP_BOT_WEBHOOK` | 企业微信群机器人 Webhook | 空 |
| `WECOM_MESSAGE_MAX_CHARS` | 单条推送最大 UTF-8 字节数 | `3000` |
| `DEDUP_SIMILARITY_THRESHOLD` | 标题相似度阈值 | `0.78` |

服务器部署时，脚本会将 `MESSAGE_CHANNEL` 设为 `wecom_group_bot` 并启用调度器。个人微信接收日报的方式是加入配置了机器人的企业微信群；个人微信网关适配器保留在 `app/channels/wechat.py`，用于需要网关的部署。

## 定时任务

启用 `ENABLE_SCHEDULER=true` 后：

- RSS 新闻按 `NEWS_COLLECTION_INTERVAL_MINUTES` 周期采集，服务启动时执行一次。
- 每天 `09:00`（`Asia/Shanghai`）生成并发送日报。
- Redis 锁和 `daily_digests(user_id, digest_date)` 唯一约束防止重复生成。
- 单个 RSS 源失败不会阻断其他源；失败状态写入 `tasks`。

日报推送只展示有新闻的领域，不再输出“今日头条”或游戏栏目。标题、摘要和趋势文本会清理点赞/评论指标；DeepSeek 返回缺少中文字段时，会追加中文翻译请求。DeepSeek 不可用时，系统会回退到 RSS 原文。

## API

启动后可通过 `/docs` 查看 OpenAPI 文档。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/health` | 服务存活检查 |
| `POST` | `/api/agent/chat` | 使用 Tool Calling 查询新闻 |
| `POST` | `/api/digest/generate` | 手动生成日报，可传 `digest_date` |
| `POST` | `/api/wechat/webhook` | 接收微信网关转发的消息 |

`/api/wechat/webhook` 可通过 `WECHAT_WEBHOOK_TOKEN` 校验请求。企业微信群机器人是出站推送渠道，不需要接收回调。

## 项目结构

```text
app/
├── agent/       # Agent、Tool Registry、Planner、Memory
├── api/         # FastAPI 路由
├── channels/    # 微信和企业微信消息适配器、日报发送
├── collectors/  # BaseCollector、RSSCollector
├── db/          # 数据库会话、迁移入口、RSS seed
├── llm/         # LLMClient、DeepSeek、Pydantic 输出模型
├── models/      # SQLAlchemy ORM 模型
├── scheduler/   # APScheduler 任务
├── services/    # 采集、入库、去重、聚类、查询、日报
├── runtime.py   # 运行时依赖组合
└── main.py      # FastAPI 应用入口
db/migrations/   # Alembic migration
docker/          # Nginx 配置
prompts/         # Agent prompt 模板
tests/           # 单元测试和 API 测试
```

## 本地开发

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\\Scripts\\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
cp .env.example .env            # Windows: Copy-Item .env.example .env
pytest
uvicorn app.main:app --reload
```

本地运行需要可访问的 PostgreSQL 和 Redis；只运行测试不需要真实 DeepSeek、新闻网站或微信凭据，测试使用 Mock 客户端。

数据库命令：

```bash
alembic upgrade head
python -m app.db.init_db
alembic downgrade base
```

## 测试与代码质量

```bash
pytest
ruff check app tests
mypy app
```

测试覆盖采集器、URL 入库去重、新闻去重、事件聚类、DeepSeek 错误处理、Agent 工具、日报幂等、微信推送和 API 接线。测试不会调用真实外部服务。

## 安全与已知限制

- `.env`、API Key、数据库密码和微信 Webhook 不得提交到 Git。
- DeepSeek 摘要严格要求基于新闻内容；模型失败时使用 RSS 原文回退。
- RSS 源质量和网络可达性会影响新闻数量；源失败会被隔离并记录日志。
- `/health` 是存活检查，不等同于 PostgreSQL、Redis 和 DeepSeek 的完整 readiness 检查。
- 管理接口鉴权、URL 白名单和更细粒度限流仍属于后续增强项。

