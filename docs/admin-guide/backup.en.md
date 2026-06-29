# Backup

SMDG backup and restore procedures.

## What to back up

| Component | Priority | Script / method |
|-----------|----------|-----------------|
| PostgreSQL | Critical | `scripts/backup.sh` |
| `encrypted/` or S3 bucket | Critical | `backup.sh` / `aws s3 sync` |
| `keys/age.key` | Critical | GPG encryption in `backup.sh` |
| `audit_logs/` | High | tar.gz in `backup.sh` |
| `secrets/` | High | copy in `backup.sh` |
| `.env` | Medium | copy in `backup.sh` |

!!! danger "age key"
    Without `age.key`, encrypted files are **unrecoverable**. Store the key separately from data backups (split custody).

## Automated backup

```bash
./scripts/backup.sh
```

Variables:

| Variable | Default |
|----------|---------|
| `BACKUP_DIR` | `/backups/smdg` |
| `RETENTION_DAYS` | `30` |
| `S3_BUCKET_ENCRYPTED` | `smdg-encrypted` |

Recommended cron:

```cron
0 2 * * * cd /opt/smdg && ./scripts/backup.sh >> /var/log/smdg-backup.log 2>&1
```

## Restore

```bash
./scripts/restore.sh
```

Before restore:

1. Stop the application (`docker compose down`).
2. Ensure `age.key` is available.
3. Restore PostgreSQL from `db_*.sql.gz`.
4. Sync `encrypted/` or the S3 bucket.
5. Start the stack and check `/health/ready`.

Detailed runbook: [runbooks/operations/backup-recovery.md](../runbooks/operations/backup-recovery.md).

## Backup testing

Quarterly, run a **test restore** on staging:

1. Deploy a clean instance.
2. Restore the latest backup.
3. Download a test file and open DICOM.

## Off-site copies

Copy `BACKUP_DIR` to a separate server or object storage with versioning and encryption at rest.
