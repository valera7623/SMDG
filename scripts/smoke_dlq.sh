#!/usr/bin/env bash
set -Eeuo pipefail

# Smoke script for DLQ flow:
#  1) alembic upgrade head
#  2) docker compose up -d
#  3) GET /api/dlq/stats
#  4) GET /api/dlq/messages
#  5) POST /api/dlq/messages/{message_id}/replay (optional; first message)
#  6) POST /api/dlq/cleanup?days=N
#
# Requires admin auth cookie in COOKIE_JAR (default: /tmp/cookies.txt).

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${PROJECT_ROOT}"

API_BASE_URL="${API_BASE_URL:-http://localhost:8000}"
COOKIE_JAR="${COOKIE_JAR:-/tmp/cookies.txt}"
CLEANUP_DAYS="${CLEANUP_DAYS:-30}"
SKIP_MIGRATIONS="${SKIP_MIGRATIONS:-false}"
SKIP_COMPOSE_UP="${SKIP_COMPOSE_UP:-false}"
AUTO_REPLAY_FIRST="${AUTO_REPLAY_FIRST:-true}"

_ts() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }
log() { printf "[%s] %s\n" "$(_ts)" "$*"; }
ok() { printf "[%s] ✅ %s\n" "$(_ts)" "$*"; }
warn() { printf "[%s] ⚠️  %s\n" "$(_ts)" "$*" >&2; }
err() { printf "[%s] ❌ %s\n" "$(_ts)" "$*" >&2; }

require_cmd() {
    local cmd="$1"
    if ! command -v "${cmd}" >/dev/null 2>&1; then
        err "Command not found: ${cmd}"
        exit 127
    fi
}

print_json_or_raw() {
    local payload="$1"
    if command -v jq >/dev/null 2>&1; then
        printf "%s" "${payload}" | jq .
    else
        printf "%s\n" "${payload}"
    fi
}

api_get() {
    local path="$1"
    curl -sS -b "${COOKIE_JAR}" "${API_BASE_URL}${path}"
}

api_post() {
    local path="$1"
    curl -sS -X POST -b "${COOKIE_JAR}" "${API_BASE_URL}${path}"
}

if [[ ! -f "${COOKIE_JAR}" ]]; then
    warn "Cookie jar not found: ${COOKIE_JAR}"
    warn "DLQ admin API requires authenticated admin cookie."
fi

require_cmd curl
require_cmd docker
require_cmd alembic

if [[ "${SKIP_MIGRATIONS}" != "true" ]]; then
    log "Running migrations: alembic upgrade head"
    alembic upgrade head
    ok "Migrations applied"
else
    warn "Skipping migrations (SKIP_MIGRATIONS=true)"
fi

if [[ "${SKIP_COMPOSE_UP}" != "true" ]]; then
    log "Starting services: docker compose up -d"
    docker compose up -d
    ok "docker compose up completed"
else
    warn "Skipping docker compose up (SKIP_COMPOSE_UP=true)"
fi

log "DLQ stats:"
STATS_JSON="$(api_get "/api/dlq/stats")"
print_json_or_raw "${STATS_JSON}"

log "DLQ messages:"
MESSAGES_JSON="$(api_get "/api/dlq/messages?limit=50&offset=0")"
print_json_or_raw "${MESSAGES_JSON}"

MESSAGE_ID=""
if command -v jq >/dev/null 2>&1; then
    MESSAGE_ID="$(printf "%s" "${MESSAGES_JSON}" | jq -r '.messages[0].message_id // empty')"
fi

if [[ "${AUTO_REPLAY_FIRST}" == "true" ]]; then
    if [[ -n "${MESSAGE_ID}" ]]; then
        log "Replay first message: ${MESSAGE_ID}"
        REPLAY_JSON="$(api_post "/api/dlq/messages/${MESSAGE_ID}/replay")"
        print_json_or_raw "${REPLAY_JSON}"
    else
        warn "No message_id found for replay (or jq missing)."
        warn "Manual replay example:"
        warn "curl -X POST \"${API_BASE_URL}/api/dlq/messages/{message_id}/replay\" -b \"${COOKIE_JAR}\""
    fi
else
    warn "Skipping replay step (AUTO_REPLAY_FIRST=false)"
fi

log "Cleanup old messages: days=${CLEANUP_DAYS}"
CLEANUP_JSON="$(api_post "/api/dlq/cleanup?days=${CLEANUP_DAYS}")"
print_json_or_raw "${CLEANUP_JSON}"

ok "DLQ smoke flow finished"
