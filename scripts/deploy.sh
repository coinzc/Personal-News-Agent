#!/usr/bin/env bash

# One-command Ubuntu deployment for Personal News Agent.
# This script is intentionally idempotent: it preserves .env and Docker volumes.

set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DOCKER=1
ALLOW_INCOMPLETE=0
HEALTH_TIMEOUT=180

log() {
  printf '[deploy] %s\n' "$*"
}

fail() {
  printf '[deploy] ERROR: %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'EOF'
Usage: sudo bash scripts/deploy.sh [options]

Options:
  --skip-docker-install  Do not install Docker when it is missing.
  --allow-incomplete     Start without DeepSeek or WeCom credentials.
  --health-timeout SEC   Maximum seconds to wait for /health (default: 180).
  -h, --help             Show this help.

The script preserves .env and Docker volumes on repeated runs.
EOF
}

while (($# > 0)); do
  case "$1" in
    --skip-docker-install) INSTALL_DOCKER=0 ;;
    --allow-incomplete) ALLOW_INCOMPLETE=1 ;;
    --health-timeout)
      (($# >= 2)) || fail "--health-timeout requires a value"
      HEALTH_TIMEOUT="$2"
      shift
      ;;
    -h|--help) usage; exit 0 ;;
    *) fail "unknown option: $1 (use --help for usage)" ;;
  esac
  shift
done

[[ "$(id -u)" -eq 0 ]] || fail "run as root or with sudo: sudo bash scripts/deploy.sh"
cd "$PROJECT_DIR"

command -v curl >/dev/null 2>&1 || fail "curl is required"
command -v openssl >/dev/null 2>&1 || fail "openssl is required"

install_docker() {
  [[ "$INSTALL_DOCKER" -eq 1 ]] || fail "Docker is missing; install Docker or remove --skip-docker-install"
  [[ -f /etc/os-release ]] || fail "cannot detect Linux distribution"
  # shellcheck disable=SC1091
  source /etc/os-release
  [[ "${ID:-}" == "ubuntu" ]] || fail "automatic Docker installation supports Ubuntu only (detected: ${ID:-unknown})"

  log "Installing Docker Engine and Compose plugin"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y ca-certificates curl gnupg
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    | gpg --dearmor --yes -o /etc/apt/keyrings/docker.gpg
  chmod a+r /etc/apt/keyrings/docker.gpg
  printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu %s stable\n' \
    "$(dpkg --print-architecture)" "${VERSION_CODENAME}" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  systemctl enable --now docker
}

if ! command -v docker >/dev/null 2>&1; then
  install_docker
fi
docker compose version >/dev/null 2>&1 || fail "Docker Compose v2 plugin is unavailable"
systemctl is-active --quiet docker || systemctl enable --now docker

if [[ ! -f .env ]]; then
  log "Creating .env from .env.example"
  install -m 600 .env.example .env
else
  chmod 600 .env
  log "Keeping existing .env"
fi

set_env() {
  local key="$1"
  local value="$2"
  local escaped
  escaped="$(printf '%s' "$value" | sed 's/[\\&|]/\\&/g')"
  if grep -qE "^${key}=" .env; then
    sed -i "s|^${key}=.*|${key}=${escaped}|" .env
  else
    printf '%s=%s\n' "$key" "$value" >> .env
  fi
}

read_existing_env() {
  local key="$1"
  awk -F= -v wanted="$key" '$1 == wanted {sub(/^[^=]*=/, ""); value=$0} END {print value}' .env
}

prompt_secret() {
  local key="$1"
  local prompt="$2"
  local current
  current="$(read_existing_env "$key")"
  if [[ -n "$current" && "$current" != "replace-me" && "$current" != "your-real-deepseek-key" ]]; then
    return
  fi
  if [[ ! -t 0 ]]; then
    [[ "$ALLOW_INCOMPLETE" -eq 1 ]] || fail "$key is not configured; use an interactive terminal or --allow-incomplete"
    return
  fi
  local value
  read -r -s -p "$prompt: " value
  printf '\n'
  if [[ -n "$value" ]]; then
    set_env "$key" "$value"
  elif [[ "$ALLOW_INCOMPLETE" -eq 0 ]]; then
    fail "$key cannot be empty"
  fi
}

POSTGRES_PASSWORD="$(read_existing_env POSTGRES_PASSWORD)"
if [[ -z "$POSTGRES_PASSWORD" || "$POSTGRES_PASSWORD" == "change-me" ]]; then
  POSTGRES_PASSWORD="$(openssl rand -hex 24)"
  set_env POSTGRES_PASSWORD "$POSTGRES_PASSWORD"
fi
POSTGRES_DB="$(read_existing_env POSTGRES_DB)"
POSTGRES_USER="$(read_existing_env POSTGRES_USER)"
set_env POSTGRES_DB "${POSTGRES_DB:-news_agent}"
set_env POSTGRES_USER "${POSTGRES_USER:-news_agent}"
set_env DATABASE_URL "postgresql+asyncpg://${POSTGRES_USER:-news_agent}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB:-news_agent}"
set_env REDIS_URL "redis://redis:6379/0"
set_env APP_ENV production
set_env DEBUG false
set_env TIMEZONE Asia/Singapore
set_env MESSAGE_CHANNEL wecom_group_bot
set_env ENABLE_SCHEDULER true

prompt_secret DEEPSEEK_API_KEY "Enter DeepSeek API key (hidden)"
prompt_secret WECOM_GROUP_BOT_WEBHOOK "Enter Enterprise WeChat group bot webhook (hidden)"

log "Validating Compose configuration"
docker compose config >/dev/null

log "Building and starting services"
docker compose up -d --build

log "Waiting for PostgreSQL and Redis health checks"
deadline=$((SECONDS + HEALTH_TIMEOUT))
postgres_status=""
redis_status=""
while ((SECONDS < deadline)); do
  postgres_status="$(docker compose ps --status running --format '{{.Service}} {{.Health}}' postgres 2>/dev/null || true)"
  redis_status="$(docker compose ps --status running --format '{{.Service}} {{.Health}}' redis 2>/dev/null || true)"
  if [[ "$postgres_status" == *healthy* && "$redis_status" == *healthy* ]]; then
    break
  fi
  sleep 3
done
[[ "$postgres_status" == *healthy* ]] || fail "PostgreSQL did not become healthy; inspect: docker compose logs postgres"
[[ "$redis_status" == *healthy* ]] || fail "Redis did not become healthy; inspect: docker compose logs redis"

sync_database_password() {
  [[ "$POSTGRES_USER" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || fail "POSTGRES_USER contains unsupported characters"
  log "Synchronizing PostgreSQL role password with .env"
  # The official PostgreSQL image allows local socket access from inside the
  # database container. This updates an existing named volume when .env was
  # regenerated, without deleting any database data.
  docker compose exec -T postgres psql \
    -U "$POSTGRES_USER" \
    -d "$POSTGRES_DB" \
    -v ON_ERROR_STOP=1 \
    -v app_password="$POSTGRES_PASSWORD" \
    -c "ALTER ROLE \"$POSTGRES_USER\" PASSWORD :'app_password';"
}

sync_database_password

log "Applying database migrations"
docker compose exec -T backend python -m app.db.init_db

log "Waiting for HTTP health endpoint"
deadline=$((SECONDS + HEALTH_TIMEOUT))
until curl -fsS http://127.0.0.1/health >/dev/null 2>&1; do
  ((SECONDS < deadline)) || fail "backend did not become healthy; inspect: docker compose logs backend"
  sleep 3
done

log "Deployment completed"
log "API: http://$(hostname -I 2>/dev/null | awk '{print $1}' || printf 'SERVER_IP')/docs"
log "Health: http://127.0.0.1/health"
log "Logs: docker compose logs -f --tail=200 backend"
