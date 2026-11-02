# Ubuntu Deployment Guide

Use Ubuntu 22.04 or 24.04 and Docker Compose.

## Docker Setup

```bash
sudo apt update
sudo apt install -y ca-certificates curl git ufw openssl
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"
```

Log in again, then check:

```bash
docker version
docker compose version
```

## Project and Configuration

For a one-command deployment from an already cloned checkout, run:

```bash
sudo bash scripts/deploy.sh
```

The script installs Docker on Ubuntu when needed, creates `.env` with mode `600`, generates a database password, reads the DeepSeek key and Enterprise WeChat group bot webhook without echoing them, starts the stack, synchronizes the PostgreSQL role password with `.env`, runs migrations, and checks `/health`. Re-running it preserves `.env` and named volumes. Use `--allow-incomplete` only for an infrastructure smoke test without external credentials.

```bash
sudo mkdir -p /opt/personal-news-agent
sudo chown -R "$USER":"$USER" /opt/personal-news-agent
cd /opt/personal-news-agent
git clone YOUR_REPOSITORY_URL .
cp .env.example .env
chmod 600 .env
nano .env
```

Set these values in `.env`:

```dotenv
APP_ENV=production
DEBUG=false
TIMEZONE=Asia/Singapore
POSTGRES_DB=news_agent
POSTGRES_USER=news_agent
POSTGRES_PASSWORD=replace-with-a-strong-password
DATABASE_URL=postgresql+asyncpg://news_agent:replace-with-a-strong-password@postgres:5432/news_agent
REDIS_URL=redis://redis:6379/0
DEEPSEEK_API_KEY=your-real-deepseek-key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
ENABLE_SCHEDULER=true
MESSAGE_CHANNEL=wecom_group_bot
WECOM_GROUP_BOT_WEBHOOK=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=replace-me
WECOM_MESSAGE_TYPE=markdown
WECOM_MESSAGE_MAX_CHARS=3500
WECOM_TIMEOUT=15
WECOM_MAX_RETRIES=3
WECOM_BACKOFF_FACTOR=0.5
# Legacy personal-WeChat gateway settings; leave empty when using WeCom
WECHAT_GATEWAY_ENDPOINT=
WECHAT_GATEWAY_TOKEN=outbound-random-token
WECHAT_RECIPIENT=your-gateway-user-id
WECHAT_WEBHOOK_TOKEN=inbound-random-token
WECHAT_MESSAGE_MAX_CHARS=3500
```

Generate separate outbound and inbound tokens:

```bash
openssl rand -hex 32
```

## Start

```bash
cd /opt/personal-news-agent
docker compose up -d --build
docker compose ps
docker compose exec backend python -m app.db.init_db
curl -f http://127.0.0.1/health
```

Logs:

```bash
docker compose logs -f --tail=200 backend
```

## Enterprise WeChat Group Bot

The recommended deployment uses an Enterprise WeChat group bot. Create a dedicated group, add the receiving personal WeChat account, add a group bot, and copy its webhook into `WECOM_GROUP_BOT_WEBHOOK`. The project does not control a personal WeChat client directly and never needs a personal WeChat password or QR login.

Test delivery with the manual digest endpoint before enabling the scheduler. Keep `.env` readable only by the service account and never commit the webhook URL.

Inbound gateway request:

```text
POST https://YOUR_DOMAIN/api/wechat/webhook
X-WeChat-Webhook-Token: WECHAT_WEBHOOK_TOKEN
Content-Type: application/json
```

```json
{"sender_id":"wx-user-001","content":"What are today's important news?"}
```

The project returns an Agent response in JSON. The gateway sends its `content` back to WeChat.

Outbound digest request made by the project:

```text
POST WECHAT_GATEWAY_ENDPOINT
Authorization: Bearer WECHAT_GATEWAY_TOKEN
```

```json
{"recipient":"WECHAT_RECIPIENT","content":"Daily news digest text"}
```

## Security

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

Do not expose PostgreSQL port 5432 or Redis port 6379. Use HTTPS for the webhook. The bundled Nginx listens on port 80; add TLS at the host/proxy layer or use Certbot after DNS points to this server.

The bundled Nginx resolves the Compose service name `backend` through Docker's embedded DNS (`127.0.0.11`) at request time. This avoids stale backend container IPs during container replacement.

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d YOUR_DOMAIN
```

## Operations

```bash
docker compose ps
docker compose logs -f --tail=200 backend
docker compose restart backend
```

Upgrade:

```bash
git pull
docker compose up -d --build
docker compose exec backend python -m app.db.init_db
```

Backup:

```bash
mkdir -p backups
docker compose exec -T postgres pg_dump -U news_agent -d news_agent > backups/news_agent_$(date +%Y%m%d_%H%M%S).sql
```

Do not run `docker compose down -v` unless you intend to delete database and Redis data.

## Troubleshooting

- Agent returns 503: configure `DEEPSEEK_API_KEY` and restart backend.
- Digest contains no articles: collect news into PostgreSQL first.
- WeChat fails: check gateway endpoint, outbound token and recipient.
- Webhook returns 401: check `X-WeChat-Webhook-Token`.
- Backend fails: inspect `docker compose logs backend postgres redis`.

## Current Scope

The app exposes `/health`, `/api/agent/chat`, `/api/digest/generate` and `/api/wechat/webhook`. With `ENABLE_SCHEDULER=true`, it runs daily digest generation and delivery at 09:00 Asia/Singapore. Production collection jobs still need scheduler registration.
