#!/usr/bin/env bash
# Blue/Green cutover for edge nginx with auto-rollback.
#
# Workflow:
#  1) Backup current nginx config inside edge container.
#  2) Replace upstream URL/host (BLUE -> GREEN) in config.
#  3) Validate config (nginx -t) and reload.
#  4) Run health checks via public endpoint.
#  5) Auto-rollback on any failure.
#
# Example:
#   EDGE_NGINX_CONTAINER=smdg-nginx-1 \
#   NGINX_CONF_PATH=/etc/nginx/conf.d/default.conf \
#   BLUE_UPSTREAM=http://smdg:8000 \
#   GREEN_UPSTREAM=http://host.docker.internal:8080 \
#   PUBLIC_HEALTH_URL=http://localhost/health/ready \
#   ./scripts/cutover_edge.sh

set -Eeuo pipefail

EDGE_NGINX_CONTAINER="${EDGE_NGINX_CONTAINER:-smdg-nginx-1}"
NGINX_CONF_PATH="${NGINX_CONF_PATH:-/etc/nginx/conf.d/default.conf}"
BLUE_UPSTREAM="${BLUE_UPSTREAM:-http://smdg:8000}"
GREEN_UPSTREAM="${GREEN_UPSTREAM:-http://host.docker.internal:8080}"
PUBLIC_HEALTH_URL="${PUBLIC_HEALTH_URL:-http://localhost/health/ready}"
HEALTH_TIMEOUT_SECONDS="${HEALTH_TIMEOUT_SECONDS:-3}"
HEALTH_RETRIES="${HEALTH_RETRIES:-20}"
HEALTH_SLEEP_SECONDS="${HEALTH_SLEEP_SECONDS:-2}"

BACKUP_PATH="${NGINX_CONF_PATH}.pre-cutover.$(date +%Y%m%d%H%M%S)"
ROLLED_BACK=0

log() { printf "\033[1;34m[%s]\033[0m %s\n" "$(date +%H:%M:%S)" "$*"; }
ok()  { printf "\033[1;32m✅ %s\033[0m\n" "$*"; }
err() { printf "\033[1;31m❌ %s\033[0m\n" "$*" >&2; }

rollback() {
  if [[ "${ROLLED_BACK}" -eq 1 ]]; then
    return 0
  fi
  ROLLED_BACK=1
  err "Rolling back nginx config..."
  docker exec "${EDGE_NGINX_CONTAINER}" sh -lc \
    "cp '${BACKUP_PATH}' '${NGINX_CONF_PATH}' && nginx -t && nginx -s reload" >/dev/null
  ok "Rollback complete"
}

trap 'err "Cutover failed (line ${LINENO})"; rollback; exit 1' ERR

log "Edge container: ${EDGE_NGINX_CONTAINER}"
log "Config path: ${NGINX_CONF_PATH}"
log "Switch: ${BLUE_UPSTREAM} -> ${GREEN_UPSTREAM}"

docker inspect "${EDGE_NGINX_CONTAINER}" >/dev/null

log "Backing up current nginx config..."
docker exec "${EDGE_NGINX_CONTAINER}" sh -lc \
  "cp '${NGINX_CONF_PATH}' '${BACKUP_PATH}'"

log "Applying upstream replacement..."
docker exec "${EDGE_NGINX_CONTAINER}" sh -lc \
  "if ! grep -q '${BLUE_UPSTREAM}' '${NGINX_CONF_PATH}'; then echo 'source upstream not found'; exit 2; fi"
docker exec "${EDGE_NGINX_CONTAINER}" sh -lc \
  "sed -i 's#${BLUE_UPSTREAM}#${GREEN_UPSTREAM}#g' '${NGINX_CONF_PATH}'"

log "Validating nginx config..."
docker exec "${EDGE_NGINX_CONTAINER}" nginx -t >/dev/null

log "Reloading nginx..."
docker exec "${EDGE_NGINX_CONTAINER}" nginx -s reload >/dev/null

log "Checking public health endpoint: ${PUBLIC_HEALTH_URL}"
attempt=1
while (( attempt <= HEALTH_RETRIES )); do
  if curl -fsS --max-time "${HEALTH_TIMEOUT_SECONDS}" "${PUBLIC_HEALTH_URL}" >/dev/null 2>&1; then
    ok "Cutover successful; health check passed on attempt ${attempt}"
    exit 0
  fi
  log "Health check attempt ${attempt}/${HEALTH_RETRIES} failed, retrying..."
  sleep "${HEALTH_SLEEP_SECONDS}"
  attempt=$((attempt + 1))
done

err "Health checks failed after ${HEALTH_RETRIES} attempts"
rollback
exit 1
