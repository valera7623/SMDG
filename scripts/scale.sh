#!/usr/bin/env bash
# Scale SMDG horizontally in docker-compose.scale.yml

set -Eeuo pipefail

REPLICAS="${1:-3}"
COMPOSE_FILE="docker-compose.scale.yml"

echo "🚀 Scaling SMDG to ${REPLICAS} instances"

docker compose -f "${COMPOSE_FILE}" up -d --scale smdg="${REPLICAS}"

echo "⏳ Waiting for instances to be healthy..."
for i in $(seq 1 "${REPLICAS}"); do
  cname="$(docker compose -f "${COMPOSE_FILE}" ps -q smdg | sed -n "${i}p")"
  if [[ -z "${cname}" ]]; then
    echo "❌ Could not find container id for replica ${i}"
    exit 1
  fi
  echo "Waiting for replica ${i} (${cname:0:12})..."
  until docker exec "${cname}" curl -fsS http://localhost:8000/health/ready >/dev/null 2>&1; do
    sleep 2
  done
  echo "✅ Replica ${i} ready"
done

echo "🔄 Reloading nginx load balancer..."
docker compose -f "${COMPOSE_FILE}" exec -T nginx-lb nginx -s reload

echo "✅ Scaling complete: ${REPLICAS} instances running"
