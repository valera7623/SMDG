#!/usr/bin/env bash
# First-time creation of Docker secret files under ./secrets/ (not committed to git).
# Run on the VPS once after git clone, before `docker compose up`.
#
# Requirements: openssl; optional `age` (age-keygen) for age keys — if missing, install age or use packages.
#
# Usage:
#   ./scripts/vps-bootstrap-secrets.sh
# Non-interactive (e.g. automation):
#   ADMIN_PASSWORD=... POSTGRES_PASSWORD=... JWT_SECRET_KEY=... ./scripts/vps-bootstrap-secrets.sh

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SECRETS_DIR="${ROOT}/secrets"
mkdir -p "${SECRETS_DIR}"
chmod 700 "${SECRETS_DIR}"

rand_hex() { openssl rand -hex "${1:?}"; }

generate_jwt() {
  if [[ -n "${JWT_SECRET_KEY:-}" ]]; then
    printf '%s' "${JWT_SECRET_KEY}"
    return
  fi
  # 48+ chars required by entrypoint.sh
  openssl rand -base64 48 | tr -d '\n'
}

generate_age_key() {
  if command -v age-keygen >/dev/null 2>&1; then
    age-keygen -o "${SECRETS_DIR}/age.key"
    chmod 600 "${SECRETS_DIR}/age.key"
    cp -a "${SECRETS_DIR}/age.key" "${ROOT}/keys/age.key" 2>/dev/null || {
      mkdir -p "${ROOT}/keys"
      cp -a "${SECRETS_DIR}/age.key" "${ROOT}/keys/age.key"
      chmod 600 "${ROOT}/keys/age.key"
    }
    echo "age.key generated with age-keygen"
    return
  fi
  echo "age-keygen not found; install age (https://github.com/FiloSottile/age) or place secrets/age.key manually." >&2
  exit 1
}

if [[ ! -f "${SECRETS_DIR}/jwt_secret.txt" ]]; then
  generate_jwt > "${SECRETS_DIR}/jwt_secret.txt"
  chmod 600 "${SECRETS_DIR}/jwt_secret.txt"
  echo "Created secrets/jwt_secret.txt"
else
  echo "Keeping existing secrets/jwt_secret.txt"
fi

if [[ ! -f "${SECRETS_DIR}/postgres_password.txt" ]]; then
  if [[ -n "${POSTGRES_PASSWORD:-}" ]]; then
    printf '%s' "${POSTGRES_PASSWORD}" > "${SECRETS_DIR}/postgres_password.txt"
  else
    rand_hex 24 > "${SECRETS_DIR}/postgres_password.txt"
  fi
  chmod 600 "${SECRETS_DIR}/postgres_password.txt"
  echo "Created secrets/postgres_password.txt"
else
  echo "Keeping existing secrets/postgres_password.txt"
fi

if [[ ! -f "${SECRETS_DIR}/admin_password.txt" ]]; then
  if [[ -n "${ADMIN_PASSWORD:-}" ]]; then
    printf '%s' "${ADMIN_PASSWORD}" > "${SECRETS_DIR}/admin_password.txt"
  else
    rand_hex 18 > "${SECRETS_DIR}/admin_password.txt"
    echo "Generated random admin password (save secrets/admin_password.txt securely)."
  fi
  chmod 600 "${SECRETS_DIR}/admin_password.txt"
  echo "Created secrets/admin_password.txt"
else
  echo "Keeping existing secrets/admin_password.txt"
fi

if [[ ! -f "${SECRETS_DIR}/age.key" ]]; then
  generate_age_key
else
  echo "Keeping existing secrets/age.key"
fi

echo "Bootstrap complete. Review DEV_MODE and DEPLOYMENT_TYPE in .env, then: docker compose up -d --build"
