#!/usr/bin/env bash
# Issue or renew Let's Encrypt certificates for the Docker/nginx deployment.

set -euo pipefail

read_env_file_value() {
  local name="$1"
  local env_file="${ENV_FILE:-.env}"
  if [ ! -f "$env_file" ]; then
    return 0
  fi
  awk -F= -v key="$name" '
    $0 !~ /^[[:space:]]*#/ && $1 == key {
      value = substr($0, index($0, "=") + 1)
      gsub(/^["'\'' ]+|["'\'' ]+$/, "", value)
      print value
      exit
    }
  ' "$env_file"
}

DOMAIN="${DOMAIN:-$(read_env_file_value DOMAIN)}"
LETSENCRYPT_EMAIL="${LETSENCRYPT_EMAIL:-$(read_env_file_value LETSENCRYPT_EMAIL)}"
CERTBOT_IMAGE="${CERTBOT_IMAGE:-certbot/certbot:latest}"
LETSENCRYPT_STAGING="${LETSENCRYPT_STAGING:-false}"
COMPOSE_ARGS="${COMPOSE_ARGS:--f docker-compose.yml -f docker-compose.prod.yml}"
NGINX_RESTART_AFTER_CERT_UPDATE="${NGINX_RESTART_AFTER_CERT_UPDATE:-true}"
NGINX_CERT_UPDATE_ACTION="${NGINX_CERT_UPDATE_ACTION:-reload}" # reload | restart

cert_checksum() {
  if [ -f certs/fullchain.pem ] && [ -f certs/privkey.pem ]; then
    sha256sum certs/fullchain.pem certs/privkey.pem | sha256sum | awk '{print $1}'
  fi
}

restart_nginx_after_certificate_update() {
  if [ "${NGINX_RESTART_AFTER_CERT_UPDATE}" != "true" ]; then
    return 0
  fi

  case "${NGINX_CERT_UPDATE_ACTION}" in
    reload)
      # shellcheck disable=SC2086
      docker compose ${COMPOSE_ARGS} exec -T nginx nginx -s reload || {
        echo "nginx reload failed; restarting nginx container" >&2
        # shellcheck disable=SC2086
        docker compose ${COMPOSE_ARGS} restart nginx
      }
      ;;
    restart)
      # shellcheck disable=SC2086
      docker compose ${COMPOSE_ARGS} restart nginx
      ;;
    *)
      echo "Unsupported NGINX_CERT_UPDATE_ACTION=${NGINX_CERT_UPDATE_ACTION}; use reload or restart" >&2
      exit 1
      ;;
  esac
}

if [ -z "${DOMAIN}" ]; then
  echo "DOMAIN is required (export it or set it in .env)" >&2
  exit 1
fi

if [ -z "${LETSENCRYPT_EMAIL}" ]; then
  echo "LETSENCRYPT_EMAIL is required (export it or set it in .env)" >&2
  exit 1
fi

mkdir -p certbot/www certbot/letsencrypt certs
before_checksum="$(cert_checksum || true)"

certbot_args=(
  certonly
  --webroot
  -w /var/www/certbot
  -d "${DOMAIN}"
  --email "${LETSENCRYPT_EMAIL}"
  --agree-tos
  --non-interactive
  --keep-until-expiring
)

if [ "${LETSENCRYPT_STAGING}" = "true" ]; then
  certbot_args+=(--staging)
fi

docker run --rm \
  -v "${PWD}/certbot/www:/var/www/certbot" \
  -v "${PWD}/certbot/letsencrypt:/etc/letsencrypt" \
  "${CERTBOT_IMAGE}" \
  "${certbot_args[@]}"

docker run --rm --entrypoint sh \
  -e DOMAIN="${DOMAIN}" \
  -v "${PWD}/certbot/letsencrypt:/etc/letsencrypt:ro" \
  -v "${PWD}/certs:/export-certs" \
  "${CERTBOT_IMAGE}" \
  -c 'set -eu; cp -L "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" /export-certs/fullchain.pem; cp -L "/etc/letsencrypt/live/${DOMAIN}/privkey.pem" /export-certs/privkey.pem; chmod 0644 /export-certs/fullchain.pem; chmod 0600 /export-certs/privkey.pem'

after_checksum="$(cert_checksum || true)"
if [ "${before_checksum}" != "${after_checksum}" ]; then
  echo "TLS certificate changed; applying nginx ${NGINX_CERT_UPDATE_ACTION}"
  restart_nginx_after_certificate_update
else
  echo "TLS certificate is unchanged; nginx restart/reload skipped"
fi

echo "TLS certificate is ready for ${DOMAIN}: certs/fullchain.pem and certs/privkey.pem"
