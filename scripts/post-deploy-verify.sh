#!/usr/bin/env bash
# Smoke checks after deploy (run from CI or on a workstation with curl).
#
# Usage:
#   BASE_URL=https://your-domain ./scripts/post-deploy-verify.sh
#   DOMAIN=your-domain ./scripts/post-deploy-verify.sh
#   BASE_URL=https://localhost TLS_VERIFY=false ./scripts/post-deploy-verify.sh

set -euo pipefail

DOMAIN="${DOMAIN:-}"
BASE_URL="${BASE_URL:-}"
if [ -z "$BASE_URL" ]; then
  if [ -n "$DOMAIN" ]; then
    BASE_URL="https://${DOMAIN}"
  else
    BASE_URL="https://localhost"
  fi
fi
BASE_URL="${BASE_URL%/}"
PUBLIC_HOST="${PUBLIC_HOST:-}"
CHECK_REDIRECT="${CHECK_REDIRECT:-true}"
CHECK_HSTS="${CHECK_HSTS:-true}"
CHECK_PUBLIC_PORTS="${CHECK_PUBLIC_PORTS:-true}"
PUBLIC_PORTS_TO_CHECK="${PUBLIC_PORTS_TO_CHECK:-8000 9000 9001 9090 3000 16686 4317 4318}"

if [ -z "$PUBLIC_HOST" ]; then
  PUBLIC_HOST="${BASE_URL#*://}"
  PUBLIC_HOST="${PUBLIC_HOST%%/*}"
  PUBLIC_HOST="${PUBLIC_HOST%%:*}"
fi

if [ -z "${TLS_VERIFY+x}" ]; then
  TLS_VERIFY="true"
  if [ "$PUBLIC_HOST" = "localhost" ] || [ "$PUBLIC_HOST" = "127.0.0.1" ]; then
    TLS_VERIFY="false"
  fi
fi

curl_args=(-fsS --max-time 10)
curl_head_args=(-fsSI --max-time 10)
if [ "$TLS_VERIFY" = "false" ]; then
  curl_args+=(-k)
  curl_head_args+=(-k)
fi

curl_fail() {
  echo "FAIL: $*" >&2
  exit 1
}

echo "Checking ${BASE_URL}/health/live ..."
curl "${curl_args[@]}" "${BASE_URL}/health/live" >/dev/null || curl_fail "/health/live"

echo "Checking ${BASE_URL}/health/ready ..."
curl "${curl_args[@]}" "${BASE_URL}/health/ready" >/dev/null || curl_fail "/health/ready"

if [ "$CHECK_REDIRECT" = "true" ]; then
  echo "Checking HTTP to HTTPS redirect for ${PUBLIC_HOST} ..."
  redirect_headers="$(curl -fsSI --max-time 10 "http://${PUBLIC_HOST}" || true)"
  printf '%s\n' "$redirect_headers" | grep -Eiq '^location:[[:space:]]*https://' \
    || curl_fail "http://${PUBLIC_HOST} does not redirect to https://"
fi

if [ "$CHECK_HSTS" = "true" ]; then
  echo "Checking HSTS header ..."
  hsts_headers="$(curl "${curl_head_args[@]}" "${BASE_URL}/" || true)"
  printf '%s\n' "$hsts_headers" | grep -Eiq '^strict-transport-security:.*max-age=31536000.*includesubdomains.*preload' \
    || curl_fail "Strict-Transport-Security header must include max-age=31536000, includeSubDomains and preload"
fi

if [ "$CHECK_PUBLIC_PORTS" = "true" ]; then
  echo "Checking internal service ports are not publicly reachable on ${PUBLIC_HOST} ..."
  for port in $PUBLIC_PORTS_TO_CHECK; do
    if timeout 3 bash -c "</dev/tcp/${PUBLIC_HOST}/${port}" 2>/dev/null; then
      curl_fail "port ${port} is publicly reachable"
    fi
  done
fi

echo "OK — HTTPS, health endpoints, redirect, HSTS and public port checks passed."
