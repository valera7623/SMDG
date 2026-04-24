#!/usr/bin/env bash
# Full backup for SMDG
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/backups/smdg}"
DATE="$(date +%Y%m%d_%H%M%S)"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
S3_BUCKET_ENCRYPTED="${S3_BUCKET_ENCRYPTED:-smdg-encrypted}"

mkdir -p "$BACKUP_DIR"

echo "[INFO] Starting SMDG backup at $DATE"

echo "[INFO] Backing up PostgreSQL..."
docker compose exec -T db pg_dump -U smdg_user smdg | gzip > "$BACKUP_DIR/db_$DATE.sql.gz"

echo "[INFO] Backing up encrypted files from S3/MinIO bucket: $S3_BUCKET_ENCRYPTED"
mkdir -p "$BACKUP_DIR/encrypted"
aws s3 sync "s3://$S3_BUCKET_ENCRYPTED/" "$BACKUP_DIR/encrypted/" --quiet

echo "[INFO] Backing up configuration..."
cp .env "$BACKUP_DIR/env_$DATE"
for compose_file in docker-compose.yml docker-compose.prod.yml docker-compose.single.yml; do
  if [[ -f "$compose_file" ]]; then
    cp "$compose_file" "$BACKUP_DIR/${compose_file%.yml}_$DATE.yml"
  fi
done
if [[ -d secrets ]]; then
  cp -r secrets "$BACKUP_DIR/secrets_$DATE"
fi

echo "[INFO] Backing up encryption keys (encrypted)..."
if [[ -f keys/age.key ]]; then
  if [[ -f /secure/passphrase ]]; then
    gpg --batch --yes --symmetric --cipher-algo AES256 \
      --passphrase-file /secure/passphrase \
      keys/age.key -o "$BACKUP_DIR/age.key_$DATE.gpg"
  else
    echo "[WARN] /secure/passphrase not found, skipping key backup"
  fi
else
  echo "[WARN] keys/age.key not found, skipping key backup"
fi

echo "[INFO] Backing up audit logs..."
if [[ -d audit_logs ]]; then
  tar -czf "$BACKUP_DIR/audit_$DATE.tar.gz" audit_logs/
else
  echo "[WARN] audit_logs directory not found, skipping"
fi

echo "[INFO] Creating backup manifest..."
APP_VERSION="unknown"
if docker compose ps smdg >/dev/null 2>&1; then
  APP_VERSION="$(docker compose exec -T smdg python -c "import app; print(getattr(app, '__version__', 'unknown'))" 2>/dev/null || echo unknown)"
fi

cat > "$BACKUP_DIR/manifest_$DATE.txt" <<MANIFEST
Backup Date: $DATE
SMDG Version: $APP_VERSION
Components:
- PostgreSQL: $BACKUP_DIR/db_$DATE.sql.gz
- Encrypted files: $BACKUP_DIR/encrypted/
- Configuration: $BACKUP_DIR/env_$DATE
- Encryption keys: $BACKUP_DIR/age.key_$DATE.gpg
- Audit logs: $BACKUP_DIR/audit_$DATE.tar.gz
MANIFEST

ln -sfn "manifest_$DATE.txt" "$BACKUP_DIR/manifest_latest.txt"

echo "[INFO] Cleaning backups older than $RETENTION_DAYS days..."
python - "$BACKUP_DIR" "$RETENTION_DAYS" <<'PY'
import os
import re
import sys
import time

backup_dir = sys.argv[1]
retention_days = int(sys.argv[2])
max_age_seconds = retention_days * 24 * 3600
now = time.time()

patterns = [
    re.compile(r"^db_.*\.sql\.gz$"),
    re.compile(r"^env_.*$"),
    re.compile(r"^audit_.*\.tar\.gz$"),
    re.compile(r"^age\.key_.*\.gpg$"),
    re.compile(r"^manifest_.*\.txt$"),
]

for name in os.listdir(backup_dir):
    path = os.path.join(backup_dir, name)
    if not os.path.isfile(path):
        continue
    if not any(p.match(name) for p in patterns):
        continue
    age_seconds = now - os.path.getmtime(path)
    if age_seconds > max_age_seconds:
        os.remove(path)
PY

echo "[OK] Backup completed: $BACKUP_DIR/manifest_$DATE.txt"
