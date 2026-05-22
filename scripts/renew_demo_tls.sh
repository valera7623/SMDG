#!/usr/bin/env bash
# Renew Let's Encrypt certificates for the demo stack (docker-compose.demo.yml).
#
# Requires: nginx running (webroot ACME), .env with DOMAIN and LETSENCRYPT_EMAIL.
#
# Usage:
#   ./scripts/renew_demo_tls.sh
#   LETSENCRYPT_STAGING=true ./scripts/renew_demo_tls.sh   # test against staging LE
#
# Cron (install with ./scripts/install_demo_cert_cron.sh):
#   0 3 * * * cd /path/to/SMDG && ./scripts/renew_demo_tls.sh >> logs/cert-renew.log 2>&1

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.demo.yml}"
COMPOSE_ARGS=(-f "${COMPOSE_FILE}")
CERTBOT_IMAGE="${CERTBOT_IMAGE:-certbot/certbot}"
LETSENCRYPT_STAGING="${LETSENCRYPT_STAGING:-false}"
NGINX_RELOAD="${NGINX_RELOAD:-true}"

read_env_file_value() {
  local name="$1"
  local env_file="${ENV_FILE:-.env}"
  if [ ! -f "${env_file}" ]; then
    return 0
  fi
  awk -F= -v key="${name}" '
    $0 !~ /^[[:space:]]*#/ && $1 == key {
      value = substr($0, index($0, "=") + 1)
      gsub(/^["'\'' ]+|["'\'' ]+$/, "", value)
      print value
      exit
    }
  ' "${env_file}"
}

DOMAIN="${DOMAIN:-$(read_env_file_value DOMAIN)}"

if [ -z "${DOMAIN}" ]; then
  echo "DOMAIN is required (set in .env or export DOMAIN=...)" >&2
  exit 1
fi

mkdir -p certbot/www certs logs

# Ensure nginx is up — webroot challenge is served on port 80.
if ! docker compose "${COMPOSE_ARGS[@]}" ps nginx 2>/dev/null | grep -qE 'Up|running'; then
  echo "Starting nginx for ACME webroot..."
  docker compose "${COMPOSE_ARGS[@]}" up -d nginx
  sleep 3
fi

# Ensure nginx-facing symlinks exist before renew (first run after manual certonly).
"${ROOT_DIR}/scripts/link_le_certs.sh"

renew_args=(renew --webroot -w /var/www/certbot --quiet --no-random-sleep-on-renew)

if [ "${LETSENCRYPT_STAGING}" = "true" ]; then
  renew_args+=(--staging)
fi

echo "Running certbot renew for ${DOMAIN}..."

# shellcheck disable=SC2086
docker compose "${COMPOSE_ARGS[@]}" --profile ssl run --rm certbot "${renew_args[@]}"
renew_exit=$?

if [ "${renew_exit}" -ne 0 ]; then
  echo "certbot renew failed with exit code ${renew_exit}" >&2
  exit "${renew_exit}"
fi

# Re-apply symlinks (deploy hook also runs inside certbot; this is idempotent on host).
"${ROOT_DIR}/scripts/link_le_certs.sh"

if [ "${NGINX_RELOAD}" = "true" ]; then
  echo "Reloading nginx..."
  if docker compose "${COMPOSE_ARGS[@]}" exec -T nginx nginx -s reload; then
    echo "nginx reloaded"
  else
    echo "nginx reload failed; restarting container" >&2
    docker compose "${COMPOSE_ARGS[@]}" restart nginx
  fi
fi

echo "TLS renewal complete for ${DOMAIN}"
