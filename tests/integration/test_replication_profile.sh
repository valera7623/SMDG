#!/usr/bin/env bash
# Integration smoke test for read replicas via compose profile
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.replicas.yml}"
PROFILE="${PROFILE:-replication}"

compose() {
  docker compose -f "$COMPOSE_FILE" --profile "$PROFILE" "$@"
}

cleanup() {
  compose down -v >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "[INFO] Starting replication profile stack..."
compose up -d

echo "[INFO] Waiting for databases..."
for _ in $(seq 1 40); do
  if compose exec -T db-master pg_isready -U smdg_user -d smdg >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

./scripts/setup_replication.sh

echo "[INFO] Verifying replicas are in recovery mode..."
compose exec -T db-replica-1 psql -U smdg_user -d smdg -tAc "SELECT pg_is_in_recovery();" | rg -q "t"
compose exec -T db-replica-2 psql -U smdg_user -d smdg -tAc "SELECT pg_is_in_recovery();" | rg -q "t"

echo "[INFO] Verifying replication slots on master..."
compose exec -T db-master psql -U smdg_user -d smdg -tAc "SELECT slot_name FROM pg_replication_slots;" | rg -q "replica_1_slot"
compose exec -T db-master psql -U smdg_user -d smdg -tAc "SELECT slot_name FROM pg_replication_slots;" | rg -q "replica_2_slot"

echo "[OK] Replication profile integration test passed"
