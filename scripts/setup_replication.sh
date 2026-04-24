#!/usr/bin/env bash
# Setup PostgreSQL streaming replication for docker-compose.replicas.yml
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.replicas.yml}"
POSTGRES_USER="${POSTGRES_USER:-smdg_user}"
POSTGRES_DB="${POSTGRES_DB:-smdg}"
REPLICATION_USER="${REPLICATION_USER:-replicator}"
REPLICATION_PASSWORD="${REPLICATION_PASSWORD:-replicator_pass}"

compose() {
  docker compose -f "$COMPOSE_FILE" "$@"
}

echo "[INFO] Waiting for db-master..."
for _ in $(seq 1 30); do
  if compose exec -T db-master pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

echo "[INFO] Creating replication user and slots on master..."
compose exec -T db-master psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" <<SQL
DO
\$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${REPLICATION_USER}') THEN
        CREATE ROLE ${REPLICATION_USER} WITH REPLICATION LOGIN PASSWORD '${REPLICATION_PASSWORD}';
    ELSE
        ALTER ROLE ${REPLICATION_USER} WITH REPLICATION LOGIN PASSWORD '${REPLICATION_PASSWORD}';
    END IF;
END
\$\$;

SELECT * FROM pg_create_physical_replication_slot('replica_1_slot')
WHERE NOT EXISTS (SELECT 1 FROM pg_replication_slots WHERE slot_name='replica_1_slot');

SELECT * FROM pg_create_physical_replication_slot('replica_2_slot')
WHERE NOT EXISTS (SELECT 1 FROM pg_replication_slots WHERE slot_name='replica_2_slot');
SQL

echo "[INFO] Updating pg_hba.conf on master..."
compose exec -T db-master sh -lc "grep -q 'host replication ${REPLICATION_USER} 0.0.0.0/0 md5' /var/lib/postgresql/data/pg_hba.conf || echo 'host replication ${REPLICATION_USER} 0.0.0.0/0 md5' >> /var/lib/postgresql/data/pg_hba.conf"
compose exec -T db-master psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT pg_reload_conf();"

setup_replica() {
  local replica_name="$1"
  local slot_name="$2"

  echo "[INFO] Configuring ${replica_name} using slot ${slot_name}..."
  compose stop "$replica_name"
  compose run --rm --no-deps "$replica_name" sh -lc "rm -rf /var/lib/postgresql/data/*"

  compose exec -T db-master sh -lc "PGPASSWORD='${REPLICATION_PASSWORD}' pg_basebackup -h localhost -U ${REPLICATION_USER} -D /tmp/${replica_name}_basebackup -Fp -Xs -R -P -S ${slot_name}"

  compose cp "db-master:/tmp/${replica_name}_basebackup/." "${replica_name}:/var/lib/postgresql/data/"

  compose exec -T "$replica_name" sh -lc "cat >> /var/lib/postgresql/data/postgresql.auto.conf <<CONF
primary_conninfo = 'host=db-master port=5432 user=${REPLICATION_USER} password=${REPLICATION_PASSWORD}'
primary_slot_name = '${slot_name}'
CONF"

  compose exec -T "$replica_name" sh -lc "touch /var/lib/postgresql/data/standby.signal && chown -R postgres:postgres /var/lib/postgresql/data"
  compose start "$replica_name"
}

setup_replica db-replica-1 replica_1_slot
setup_replica db-replica-2 replica_2_slot

echo "[INFO] Replication status on master:"
compose exec -T db-master psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT client_addr, state, sync_state FROM pg_stat_replication;"

echo "[OK] Streaming replication setup completed"
