#!/usr/bin/env bash
# Lightweight operational performance probe for SMDG.

set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"
REQUESTS="${REQUESTS:-50}"

echo "Running performance probe against ${BASE_URL}"
echo "Requests: ${REQUESTS}"

start_ts=$(date +%s)
ok=0
fail=0

for _ in $(seq 1 "${REQUESTS}"); do
  code=$(curl -s -o /dev/null -w "%{http_code}" "${BASE_URL}/health" || echo "000")
  if [ "${code}" = "200" ]; then
    ok=$((ok + 1))
  else
    fail=$((fail + 1))
  fi
done

end_ts=$(date +%s)
elapsed=$((end_ts - start_ts))

if [ "${elapsed}" -eq 0 ]; then
  elapsed=1
fi

rps=$((REQUESTS / elapsed))
success_rate=$((ok * 100 / REQUESTS))

echo "-----------------------------------------"
echo "Elapsed: ${elapsed}s"
echo "RPS: ${rps}"
echo "OK: ${ok}"
echo "FAIL: ${fail}"
echo "Success rate: ${success_rate}%"
echo "-----------------------------------------"

if [ "${success_rate}" -lt 95 ]; then
  echo "Probe failed: success rate < 95%"
  exit 1
fi

echo "Probe passed"
