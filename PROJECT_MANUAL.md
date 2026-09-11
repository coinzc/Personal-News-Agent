# Personal News Agent 项目说明书

## 当前结论

项目已经实现 DeepSeek 客户端、Tool Calling Agent、日报服务和微信网关适配器，但目前还不是“填写密钥后直接端到端启动”的完成品。

当前可以：

- 启动 FastAPI 基础服务并访问 `/health`。
- 使用 `DEEPSEEK_API_KEY` 创建 `DeepSeekClient`，调用 DeepSeek OpenAI-compatible API。
- 使用 `NewsAgent` 通过 Tool Calling 查询新闻。
- 使用 `WeChatAdapter` 连接一个已批准的个人微信网关/Webhook。
- 将日报发送到微信，并记录 `sent`、`send_failed` 状态。
- 使用 PostgreSQL、Redis、Alembic 和 APScheduler 的基础组件。

当前还不能：

- `docker compose up -d` 后自动完成采集、Agent、日报和微信接收的全链路编排。
- 直接通过个人微信扫码或官方个人微信 API 接收消息。
- 通过 FastAPI API 访问 Agent 对话；当前应用只注册了 `/health`。
- 应用启动时自动创建所有依赖并启动 APScheduler。

准确说法：项目具备连接 DeepSeek 和微信网关的实现能力，也能启动基础 Web 服务；但尚未达到配置密钥后即可长期端到端运行的最终状态。

## 微信接入边界

个人微信没有适用于所有部署环境的统一官方机器人 API。当前设计为：

```text
微信网关 / Webhook -> WeChatAdapter -> DigestDeliveryService
```

本阶段不接入企业微信或公众号作为接收渠道。`WeChatAdapter` 不绑定某个 SDK，支持：

- `endpoint`：向自建或第三方微信网关发送 HTTP POST。
- `sender`：注入 Python 异步发送函数，适合测试或内部网关封装。

默认请求体为：

```json
{"recipient": "微信用户标识", "content": "要发送的文本"}
```

实际网关字段不同，只需在网关侧转换或替换适配器发送实现。

## 主要代码结构

```text
app/llm/deepseek.py             DeepSeek OpenAI-compatible 客户端
app/agent/                      Tool Calling NewsAgent、工具和会话记忆
app/services/digest_service.py  每日日报编排、Redis 锁和幂等
app/channels/base.py            MessageChannel 抽象
app/channels/wechat.py          微信网关/Webhook 适配器
app/channels/digest_delivery.py 日报发送状态持久化
app/scheduler/jobs.py           Asia/Singapore 09:00 任务定义
app/models/                     SQLAlchemy ORM 模型
app/db/                         数据库会话、初始化和迁移
tests/                          各阶段 Mock/集成测试
```

## DeepSeek 配置

复制 `.env.example` 为 `.env`，至少填写：

```dotenv
DEEPSEEK_API_KEY=你的真实密钥
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
LLM_TIMEOUT=45
LLM_MAX_RETRIES=3
LLM_BACKOFF_FACTOR=0.5
```

`DeepSeekClient` 会从环境变量读取密钥，调用 `AsyncOpenAI`，处理 timeout、429、5xx 和连接错误，解析 Tool Calling，记录 latency/token usage，并避免将密钥写入日志。真实服务器还必须能访问 `api.deepseek.com`。

最小验证代码（放在异步函数中执行）：

```python
from app.llm.deepseek import DeepSeekClient

client = DeepSeekClient()
response = await client.complete([{"role": "user", "content": "请用一句话介绍你自己"}])
print(response.content)
await client.aclose()
```

## 微信配置和发送

当前 `.env.example` 的 `WECHAT_APP_ID`/`WECHAT_APP_SECRET` 只是预留字段，不会自动创建个人微信连接。实际部署需要具体网关，例如：

```dotenv
WECHAT_GATEWAY_ENDPOINT=https://your-wechat-gateway.example/send
WECHAT_GATEWAY_TOKEN=只保存在服务器环境变量中
WECHAT_RECIPIENT=你的微信用户标识
WECHAT_MESSAGE_MAX_CHARS=3500
```

示例：

```python
wechat = WeChatAdapter(
    endpoint=settings.wechat_gateway_endpoint,
    token=settings.wechat_gateway_token,
    max_chars=settings.wechat_message_max_chars,
)
await wechat.send_text(settings.wechat_recipient, "今日新闻早报")
```

适配器提供超时、429/5xx/网络错误重试、指数退避、长消息分片和顺序发送；测试使用 `httpx.MockTransport`，不访问真实微信服务。

## 日报链路

```text
Collect -> Deduplicate -> Cluster -> Rank -> Summarize
        -> DailyDigest -> WeChatAdapter -> sent/send_failed
```

`DailyDigestService` 使用 `Asia/Singapore` 计算日期，按八大领域生成 Top 3，保留摘要、为什么重要、来源链接和时间。Redis Lock、防重复唯一约束和 `Task` 状态记录分别负责并发、幂等和失败审计。

## 当前启动方式

本地启动基础 FastAPI：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

验证：`curl http://127.0.0.1:8000/health`。

Docker 启动基础设施：

```bash
cp .env.example .env
docker compose up -d --build
docker compose ps
docker compose exec backend python -m app.db.init_db
```

Compose 会启动 backend、PostgreSQL、Redis 和 Nginx，但当前 backend 尚未自动组装并启动完整 Agent/日报/微信链路。

## 尚未端到端启动的原因

1. `app.main:create_app()` 尚未注册 DeepSeek、数据库、Redis 和微信依赖。
2. APScheduler 尚未接入 FastAPI lifespan 的启动/关闭流程。
3. 当前只注册 `/health`，没有 Agent 对话 API、日报触发 API 或微信 webhook API。
4. Collector、DigestService、Agent 和 WeChatAdapter 尚未由统一应用容器组装。
5. `.env.example` 尚未加入微信网关 endpoint、token、recipient 配置。
6. 个人微信接收必须先确定具体网关实现；仅凭 App ID/Secret 无法自动完成。

## 验证状态

当前代码验证结果：

```text
pytest                       42 passed, 1 warning
ruff check app tests         All checks passed
mypy app                     Success: no issues found in 53 source files
git diff --check             通过
```

warning 来自 FastAPI/Starlette 测试客户端兼容层的弃用提示，不影响测试结果。

## 应用 API 接线状态

当前已增加最小 API 路由：

- `POST /api/agent/chat`
- `POST /api/digest/generate`

两者通过 `app.state.agent_factory` 和 `app.state.digest_service_factory` 注入真正服务；未配置时返回 `503`，避免请求触发隐式数据库或外部 API 连接。

## 达到生产可用的推荐下一步

1. 在 Settings 中加入微信网关 endpoint、token 和 recipient。
2. 建立应用依赖容器，统一创建 DB session、Redis、DeepSeekClient 和 WeChatAdapter。
3. 在 FastAPI lifespan 启动 APScheduler，并注册 09:00 任务。
4. 增加 Agent 对话 API 和微信 webhook API。
5. 将 Collector、DigestService、DigestDeliveryService 接入任务编排。
6. 增加 DeepSeek、PostgreSQL、Redis、微信网关启动连通性检查。
7. 使用真实微信网关完成端到端联调。
