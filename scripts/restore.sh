#!/usr/bin/env bash
# Full restore for SMDG from backup manifest
set -euo pipefail

BACKUP_MANIFEST="${1:-}"
S3_BUCKET_ENCRYPTED="${S3_BUCKET_ENCRYPTED:-smdg-encrypted}"

if [[ -z "$BACKUP_MANIFEST" ]]; then
  echo "Usage: $0 <backup_manifest_file>"
  exit 1
fi

if [[ ! -f "$BACKUP_MANIFEST" ]]; then
  echo "[ERROR] Manifest not found: $BACKUP_MANIFEST"
  exit 1
fi

BACKUP_DIR="$(dirname "$BACKUP_MANIFEST")"
DATE="$(basename "$BACKUP_MANIFEST" | sed 's/^manifest_//' | sed 's/\.txt$//')"

if [[ "$DATE" == "latest" ]]; then
  DATE="$(python - "$BACKUP_MANIFEST" <<'PY'
import re
import sys

manifest = sys.argv[1]
with open(manifest, "r", encoding="utf-8") as fh:
    data = fh.read()
match = re.search(r"Backup Date:\s*(\d{8}_\d{6})", data)
print(match.group(1) if match else "")
PY
)"
fi

if [[ -z "$DATE" ]]; then
  echo "[ERROR] Could not determine backup timestamp from $BACKUP_MANIFEST"
  exit 1
fi

echo "[INFO] Starting SMDG restore from backup: $DATE"

echo "[INFO] Stopping stack..."
docker compose down

echo "[INFO] Restoring PostgreSQL..."
docker compose up -d db
sleep 10
gunzip -c "$BACKUP_DIR/db_$DATE.sql.gz" | docker compose exec -T db psql -U smdg_user smdg

echo "[INFO] Restoring encrypted files to bucket: $S3_BUCKET_ENCRYPTED"
if [[ -d "$BACKUP_DIR/encrypted" ]]; then
  aws s3 sync "$BACKUP_DIR/encrypted/" "s3://$S3_BUCKET_ENCRYPTED/" --delete --quiet
else
  echo "[WARN] Encrypted backup directory missing: $BACKUP_DIR/encrypted"
fi

echo "[INFO] Restoring configuration..."
cp "$BACKUP_DIR/env_$DATE" .env

echo "[INFO] Restoring encryption keys..."
if [[ -f "$BACKUP_DIR/age.key_$DATE.gpg" ]]; then
  if [[ ! -f /secure/passphrase ]]; then
    echo "[ERROR] /secure/passphrase not found, cannot decrypt key backup"
    exit 1
  fi
  mkdir -p keys
  gpg --batch --yes --decrypt --passphrase-file /secure/passphrase \
    "$BACKUP_DIR/age.key_$DATE.gpg" > keys/age.key
  chmod 600 keys/age.key
else
  echo "[WARN] Key backup file missing: $BACKUP_DIR/age.key_$DATE.gpg"
fi

echo "[INFO] Restoring audit logs..."
if [[ -f "$BACKUP_DIR/audit_$DATE.tar.gz" ]]; then
  tar -xzf "$BACKUP_DIR/audit_$DATE.tar.gz"
else
  echo "[WARN] Audit archive missing: $BACKUP_DIR/audit_$DATE.tar.gz"
fi

echo "[INFO] Starting stack..."
docker compose up -d

sleep 10
echo "[INFO] Validating health endpoints..."
curl -fsS http://localhost:8000/health/live
curl -fsS http://localhost:8000/health/ready

echo "[OK] Restore completed from backup: $DATE"
