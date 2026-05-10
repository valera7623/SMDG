#!/usr/bin/env bash
# Smoke checks after deploy (run from CI or on a workstation with curl).
#
# Usage:
#   BASE_URL=https://your-domain ./scripts/post-deploy-verify.sh
#   BASE_URL=http://127.0.0.1:8000 ./scripts/post-deploy-verify.sh   # direct app port

set -euo pipefail

BASE_URL="${BASE_URL:-https://localhost}"
BASE_URL="${BASE_URL%/}"

curl_fail() {
  echo "FAIL: $*" >&2
  exit 1
}

echo "Checking ${BASE_URL}/health/live ..."
curl -fsS --max-time 10 "${BASE_URL}/health/live" >/dev/null || curl_fail "/health/live"

echo "Checking ${BASE_URL}/health/ready ..."
curl -fsS --max-time 10 "${BASE_URL}/health/ready" >/dev/null || curl_fail "/health/ready"

echo "OK — live and ready endpoints responded."
