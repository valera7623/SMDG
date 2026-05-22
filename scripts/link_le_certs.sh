#!/usr/bin/env bash
# Point nginx at Let's Encrypt files under certs/live/<DOMAIN>/.
#
# Demo stack mounts ./certs as /etc/nginx/certs; nginx reads:
#   fullchain.pem, privkey.pem
# Certbot stores certificates under:
#   certs/live/<DOMAIN>/fullchain.pem (symlink into archive/)
#
# Usage:
#   DOMAIN=fileguardian.info ./scripts/link_le_certs.sh
#   ./scripts/link_le_certs.sh --copy    # copy instead of symlink (rarely needed)

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

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

USE_COPY=false
for arg in "$@"; do
  case "${arg}" in
    --copy) USE_COPY=true ;;
    -h|--help)
      echo "Usage: DOMAIN=example.com $0 [--copy]"
      exit 0
      ;;
    *)
      echo "Unknown argument: ${arg}" >&2
      exit 1
      ;;
  esac
done

DOMAIN="${DOMAIN:-$(read_env_file_value DOMAIN)}"
CERTS_DIR="${CERTS_DIR:-${ROOT_DIR}/certs}"
LIVE_DIR="${CERTS_DIR}/live/${DOMAIN}"

if [ -z "${DOMAIN}" ]; then
  echo "DOMAIN is required (export it or set it in .env)" >&2
  exit 1
fi

if [ ! -d "${LIVE_DIR}" ]; then
  echo "Certificate lineage not found: ${LIVE_DIR}" >&2
  echo "Issue a certificate first, e.g.:" >&2
  echo "  docker compose -f docker-compose.demo.yml --profile ssl run --rm certbot \\" >&2
  echo "    certonly --webroot --webroot-path /var/www/certbot \\" >&2
  echo "    -d ${DOMAIN} --email you@example.com --agree-tos --non-interactive" >&2
  exit 1
fi

for name in fullchain.pem privkey.pem; do
  if [ ! -e "${LIVE_DIR}/${name}" ]; then
    echo "Missing ${LIVE_DIR}/${name}" >&2
    exit 1
  fi
done

mkdir -p "${CERTS_DIR}"

if [ "${USE_COPY}" = true ]; then
  cp -L "${LIVE_DIR}/fullchain.pem" "${CERTS_DIR}/fullchain.pem"
  cp -L "${LIVE_DIR}/privkey.pem" "${CERTS_DIR}/privkey.pem"
  chmod 0644 "${CERTS_DIR}/fullchain.pem"
  chmod 0600 "${CERTS_DIR}/privkey.pem"
  echo "Copied LE certificates to ${CERTS_DIR}/fullchain.pem and privkey.pem"
else
  ln -sf "live/${DOMAIN}/fullchain.pem" "${CERTS_DIR}/fullchain.pem"
  ln -sf "live/${DOMAIN}/privkey.pem" "${CERTS_DIR}/privkey.pem"
  echo "Linked ${CERTS_DIR}/fullchain.pem -> live/${DOMAIN}/fullchain.pem"
  echo "Linked ${CERTS_DIR}/privkey.pem -> live/${DOMAIN}/privkey.pem"
fi

if command -v openssl >/dev/null 2>&1; then
  echo "Issuer: $(openssl x509 -in "${CERTS_DIR}/fullchain.pem" -noout -issuer 2>/dev/null | sed 's/issuer= //')"
  echo "Expires: $(openssl x509 -in "${CERTS_DIR}/fullchain.pem" -noout -enddate 2>/dev/null | sed 's/notAfter=//')"
fi
