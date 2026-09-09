# Personal News Agent

基于 FastAPI、PostgreSQL、Redis 和 DeepSeek 的个人智能新闻 Agent。系统目标是持续采集多领域新闻，完成清洗、去重、事件聚类、分类、排序和摘要，并在 `Asia/Singapore` 时区每天 09:00 生成日报，通过可插拔渠道发送。

当前仓库已完成 **Phase 2：数据库层**。Phase 1 提供 FastAPI 基础服务、环境配置、日志、Docker Compose 基础设施骨架和健康检查；Phase 2 增加 SQLAlchemy 2.x 异步数据库层、核心实体、Alembic 初始迁移和 SQLite 隔离测试。新闻采集、Agent、日报和微信适配器仍将在后续阶段加入。

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
3. 异步新闻采集
4. 多级去重与 NewsEvent
5. 事件聚类
6. DeepSeek 统一客户端与结构化输出
7. News Agent 与工具调用
8. 每日日报流水线
9. 微信适配器
10. Docker 生产化
11. 完整测试
12. 监控、限流与性能优化

每个阶段都会先检查现有结构，完成实现后运行相关测试并更新本文档。

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
