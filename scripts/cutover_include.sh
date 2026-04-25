#!/usr/bin/env bash
# Blue/Green cutover via dedicated include file (no inline sed in main config).
#
# Requires edge nginx config to contain (http context):
#   include /etc/nginx/conf.d/upstream-target.conf;
# and proxy_pass to use variable:
#   proxy_pass $smdg_upstream;
#
# Include file format:
#   map $request_uri $smdg_upstream {
#       default http://smdg:8000;
#   }
#
# Example:
#   EDGE_NGINX_CONTAINER=smdg-nginx-1 \
#   INCLUDE_PATH=/etc/nginx/conf.d/upstream-target.conf \
#   GREEN_UPSTREAM=http://host.docker.internal:8080 \
#   PUBLIC_HEALTH_URL=http://localhost/health/ready \
#   ./scripts/cutover_include.sh

set -Eeuo pipefail

EDGE_NGINX_CONTAINER="${EDGE_NGINX_CONTAINER:-smdg-nginx-1}"
INCLUDE_PATH="${INCLUDE_PATH:-/etc/nginx/conf.d/upstream-target.conf}"
NGINX_CONF_PATH="${NGINX_CONF_PATH:-/etc/nginx/conf.d/default.conf}"
BLUE_UPSTREAM="${BLUE_UPSTREAM:-http://smdg:8000}"
GREEN_UPSTREAM="${GREEN_UPSTREAM:-http://host.docker.internal:8080}"
PUBLIC_HEALTH_URL="${PUBLIC_HEALTH_URL:-http://localhost/health/ready}"
HEALTH_TIMEOUT_SECONDS="${HEALTH_TIMEOUT_SECONDS:-3}"
HEALTH_RETRIES="${HEALTH_RETRIES:-20}"
HEALTH_SLEEP_SECONDS="${HEALTH_SLEEP_SECONDS:-2}"
BOOTSTRAP_IF_MISSING="${BOOTSTRAP_IF_MISSING:-false}"
CURL_INSECURE="${CURL_INSECURE:-auto}"

BACKUP_PATH="${INCLUDE_PATH}.pre-cutover.$(date +%Y%m%d%H%M%S)"
ROLLED_BACK=0

log() { printf "\033[1;34m[%s]\033[0m %s\n" "$(date +%H:%M:%S)" "$*"; }
ok()  { printf "\033[1;32m✅ %s\033[0m\n" "$*"; }
err() { printf "\033[1;31m❌ %s\033[0m\n" "$*" >&2; }

rollback() {
  if [[ "${ROLLED_BACK}" -eq 1 ]]; then
    return 0
  fi
  ROLLED_BACK=1
  err "Rolling back include file..."
  docker exec "${EDGE_NGINX_CONTAINER}" sh -lc \
    "cp '${BACKUP_PATH}' '${INCLUDE_PATH}' && nginx -t && nginx -s reload" >/dev/null
  ok "Rollback complete"
}

trap 'err "Cutover failed (line ${LINENO})"; rollback; exit 1' ERR

docker inspect "${EDGE_NGINX_CONTAINER}" >/dev/null

log "Edge container: ${EDGE_NGINX_CONTAINER}"
log "Include file: ${INCLUDE_PATH}"
log "Switch: ${BLUE_UPSTREAM} -> ${GREEN_UPSTREAM}"

if ! docker exec "${EDGE_NGINX_CONTAINER}" sh -lc "test -f '${INCLUDE_PATH}'"; then
  if [[ "${BOOTSTRAP_IF_MISSING}" != "true" ]]; then
    err "Include file not found: ${INCLUDE_PATH}"
    err "Bootstrap once by creating file with:"
    err "  map \$request_uri \$smdg_upstream { default ${BLUE_UPSTREAM}; }"
    err "and adding to nginx config:"
    err "  include ${INCLUDE_PATH};"
    err "  proxy_pass \$smdg_upstream;"
    exit 2
  fi
  log "Bootstrapping missing include file..."
  docker exec "${EDGE_NGINX_CONTAINER}" sh -lc \
    "cat > '${INCLUDE_PATH}' <<'EOF'
map \$request_uri \$smdg_upstream {
    default ${BLUE_UPSTREAM};
}
EOF"
fi

# Validate edge config references include + variable proxy_pass.
docker exec "${EDGE_NGINX_CONTAINER}" sh -lc \
  "grep -q 'include[[:space:]]\\+${INCLUDE_PATH};' '${NGINX_CONF_PATH}'"
docker exec "${EDGE_NGINX_CONTAINER}" sh -lc \
  "grep -q 'proxy_pass[[:space:]]\\+\\\$smdg_upstream' '${NGINX_CONF_PATH}'"

log "Backing up include file..."
docker exec "${EDGE_NGINX_CONTAINER}" sh -lc "cp '${INCLUDE_PATH}' '${BACKUP_PATH}'"

log "Writing new include target..."
docker exec "${EDGE_NGINX_CONTAINER}" sh -lc \
  "cat > '${INCLUDE_PATH}' <<'EOF'
map \$request_uri \$smdg_upstream {
    default ${GREEN_UPSTREAM};
}
EOF"

log "Validating nginx config..."
docker exec "${EDGE_NGINX_CONTAINER}" nginx -t >/dev/null

log "Reloading nginx..."
docker exec "${EDGE_NGINX_CONTAINER}" nginx -s reload >/dev/null

log "Checking public health endpoint: ${PUBLIC_HEALTH_URL}"
attempt=1
curl_args=(-fsS --max-time "${HEALTH_TIMEOUT_SECONDS}")
if [[ "${CURL_INSECURE}" == "true" ]]; then
  curl_args+=(-k)
elif [[ "${CURL_INSECURE}" == "auto" && "${PUBLIC_HEALTH_URL}" == https://* ]]; then
  curl_args+=(-k)
fi
while (( attempt <= HEALTH_RETRIES )); do
  if curl "${curl_args[@]}" "${PUBLIC_HEALTH_URL}" >/dev/null 2>&1; then
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
