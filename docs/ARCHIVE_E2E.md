# Archive E2E Runbook (SMDG)

This document is the official end-to-end validation runbook for SMDG archive workflows.

Scope:
- archive old files into cold storage
- archive audit logs
- archive deleted users with anonymization
- restore archived records
- validate metrics and alerting pipeline

---

## 1) Preconditions

- Stack is up and healthy:
  - `docker compose ps`
- Migrations are applied:
  - `alembic upgrade head`
- Admin auth cookie exists (for API checks):
  - `/tmp/cookies.txt`
- Archive feature enabled in env:
  - `ARCHIVE_ENABLED=true`
- Cold storage mode selected (recommended for local E2E):
  - `COLD_STORAGE_TYPE=filesystem`

Recommended test TTL setup:
- `ARCHIVE_FILE_AGE_DAYS=0`
- `ARCHIVE_AUDIT_AGE_DAYS=0`
- `ARCHIVE_DELETED_USER_AGE_DAYS=0`

---

## 2) Baseline checks

```bash
docker compose exec -T db psql -U smdg_user -d smdg -c "\\dt archive_*"
docker compose exec -T db psql -U smdg_user -d smdg -c "\\dt deleted_users"
curl -s http://localhost:8000/api/archive/stats -b /tmp/cookies.txt | jq .
```

Expected:
- archive tables exist
- API responds with JSON

---

## 3) E2E for source_type=file (archive + restore)

### 3.1 Prepare candidate object in storage

```bash
docker compose exec -T smdg sh -lc 'printf "e2e-archive-payload-%s\\n" "$(date +%s)" > /tmp/e2e_persist_file.age'

docker compose exec -T smdg python - <<'PY'
import asyncio
from pathlib import Path
from app.core import encrypted_storage, cleanup_storage

async def main():
    meta = await encrypted_storage.upload(
        key="e2e_persist_file.age",
        file_path=Path("/tmp/e2e_persist_file.age"),
        content_type="application/octet-stream",
    )
    print("uploaded key:", meta.key, "size:", meta.size)
    print("exists_in_storage:", await encrypted_storage.exists("e2e_persist_file.age"))
    await cleanup_storage()

asyncio.run(main())
PY
```

### 3.2 Insert expired DB row for archive candidate

```bash
docker compose exec -T db psql -U smdg_user -d smdg <<'SQL'
INSERT INTO files (
  tenant_id, user_id, original_name, encrypted_name, encrypted_path,
  original_size, encrypted_size, original_hash, mime_type, uploaded_at,
  expires_at, is_archived
)
VALUES (
  1, NULL, 'e2e_persist_file.dcm', 'e2e_persist_file.age', 'e2e_persist_file.age',
  1024, 1024, 'e2e_persist_hash', 'application/dicom',
  NOW() - INTERVAL '60 days',
  NOW() - INTERVAL '31 days',
  false
);
SQL
```

### 3.3 Archive expired files

```bash
docker compose exec -T smdg python - <<'PY'
import asyncio
from app.core import init_keys, cleanup_storage
from app.services.archive_service import archive_service

async def main():
    await init_keys()
    n = await archive_service.archive_expired_files()
    print("archived_files:", n)
    await cleanup_storage()

asyncio.run(main())
PY
```

Expected:
- `archived_files > 0`

### 3.4 Restore archived file

```bash
ARCHIVE_ID=$(docker compose exec -T db psql -U smdg_user -d smdg -Atc "SELECT archive_id FROM archive_records WHERE source_type='file' ORDER BY id DESC LIMIT 1;")
echo "ARCHIVE_ID=$ARCHIVE_ID"

curl -s -X POST "http://localhost:8000/api/archive/restore/${ARCHIVE_ID}?reason=e2e_restore_test" -b /tmp/cookies.txt | jq .

for i in {1..30}; do
  JSON=$(curl -s "http://localhost:8000/api/archive/restore-requests?limit=50" -b /tmp/cookies.txt)
  STATUS=$(echo "$JSON" | jq -r --arg id "$ARCHIVE_ID" '(.requests // []) | map(select(.archive_id==$id)) | .[0].status // ""')
  echo "attempt=$i status=${STATUS:-none}"
  [ "$STATUS" = "completed" ] && break
  [ "$STATUS" = "failed" ] && echo "$JSON" | jq -r --arg id "$ARCHIVE_ID" '(.requests // []) | map(select(.archive_id==$id)) | .[0]' && exit 2
  sleep 3
done
```

Expected:
- status transitions to `completed`

### 3.5 Validate DB state

```bash
docker compose exec -T db psql -U smdg_user -d smdg -c "
SELECT archive_id, source_type, status, restored_at, restored_by
FROM archive_records
WHERE archive_id='${ARCHIVE_ID}';"
```

Expected:
- `status = restored`
- `restored_at` is not null

---

## 4) E2E for source_type=audit

```bash
docker compose exec -T smdg sh -lc 'printf "test audit line\\n" > /app/audit_logs/audit_2024-01-01.log'

docker compose exec -T smdg python - <<'PY'
import asyncio
from app.core import init_keys
from app.services.archive_service import archive_service

async def main():
    await init_keys()
    n = await archive_service.archive_old_audit_logs()
    print("archived_audit_logs:", n)

asyncio.run(main())
PY
```

Expected:
- `archived_audit_logs > 0`
- `archive_records` includes `source_type='audit'`

---

## 5) E2E for source_type=user (deleted users + anonymization)

```bash
docker compose exec -T db psql -U smdg_user -d smdg <<'SQL'
INSERT INTO deleted_users (
  original_user_id, tenant_id, username, email, role, metadata_json,
  deleted_at, is_archived
)
VALUES (
  999001, 1, 'deleted_test_user', 'deleted_test_user@example.com', 'user', '{}'::json,
  NOW() - INTERVAL '40 days', false
);
SQL

docker compose exec -T smdg python - <<'PY'
import asyncio
from app.core import init_keys
from app.services.archive_service import archive_service

async def main():
    await init_keys()
    n = await archive_service.archive_deleted_users()
    print("archived_deleted_users:", n)

asyncio.run(main())
PY
```

Expected:
- `archived_deleted_users > 0`
- `deleted_users.is_archived = true`
- user fields are anonymized

---

## 6) Metrics validation

```bash
curl -s http://localhost:8000/metrics | grep -E "archived_total|archive_failures_total|restore_duration_seconds"
```

Expected:
- `archived_total{source_type="file|audit|user"}` present
- `archive_failures_total` present
- `restore_duration_seconds_bucket/sum/count` present

---

## 7) Alerting validation

### 7.1 Prometheus rules loaded

```bash
curl -s http://localhost:9090/api/v1/rules | jq '.data.groups[] | select(.name=="smdg_archive_alerts") | .name'
```

### 7.2 Alertmanager archive routing

- Confirm route for `component="archive"` exists in `alertmanager/alertmanager.yml`
- Confirm receiver points to webhook with `?channel=archive`
- Confirm `TELEGRAM_ARCHIVE_CHAT_ID` is configured in runtime env

Optional check:
```bash
curl -s http://localhost:9093/api/v2/alerts | jq '.[] | select(.labels.component=="archive") | {alertname:.labels.alertname,status:.status.state,severity:.labels.severity}'
```

---

## 8) Troubleshooting quick map

### Error: `NoSuchKey` during file archive
- DB points to missing storage object.
- Fix candidate integrity (`encrypted_path` must exist in storage) and rerun batch.

### Error: `Public key not initialized`
- Manual script bypassed app lifespan.
- Call `await init_keys()` before archive/restore jobs.

### Restore fails with `No such file or directory: /app/archive/...`
- Filesystem cold storage is non-persistent unless mounted.
- Add volume mount: `smdg_archive:/app/archive` in compose.

---

## 9) Cleanup test data

```bash
docker compose exec -T db psql -U smdg_user -d smdg <<'SQL'
DELETE FROM archive_restore_requests WHERE archive_id IN (SELECT archive_id FROM archive_records WHERE source_id=999001 OR archive_path LIKE '%e2e_%' OR archive_path LIKE '%2024-01-01%');
DELETE FROM archive_records WHERE source_id=999001 OR archive_path LIKE '%e2e_%' OR archive_path LIKE '%2024-01-01%';
DELETE FROM deleted_users WHERE original_user_id=999001 OR username LIKE 'archived_user_999001%';
DELETE FROM files WHERE encrypted_path IN ('e2e_persist_file.age','e2e_archive_file.age') OR encrypted_name IN ('e2e_persist_file.age','e2e_archive_file.age');
SQL

docker compose exec -T smdg sh -lc 'rm -f /app/encrypted/e2e_persist_file.age /app/encrypted/e2e_archive_file.age /app/audit_logs/audit_2024-01-01.log'
```

---

## 10) Release sign-off criteria

Archive feature is considered release-ready when all below are true:
- file, audit, user archive batches succeed (`>0` on prepared test data)
- restore transitions `pending -> processing -> completed`
- `archive_records` and `archive_restore_requests` reflect correct statuses
- metrics are present and changing
- archive alerts are loaded and routed to dedicated archive channel

