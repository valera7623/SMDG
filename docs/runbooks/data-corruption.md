# Runbook: Data Corruption

## Target
- RTO: 2 hours
- RPO: 15 minutes

## Symptoms
- Invalid records / checksum mismatch
- Query errors from specific tables
- Inconsistent file metadata to object storage

## Diagnosis
```bash
docker compose exec -T db psql -U smdg_user -d smdg -c "SELECT NOW();"
# Run integrity checks relevant for affected tables/files
```

## Recovery
```bash
# 1) Identify impacted window
# 2) Restore to isolated environment
./scripts/restore.sh /backups/smdg/manifest_<TIMESTAMP>.txt

# 3) Validate and promote recovered state
curl -f http://localhost:8000/health/ready
```

## Escalation
- Incident Commander approves rollback point selection.
