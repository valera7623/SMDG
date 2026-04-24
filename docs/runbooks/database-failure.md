# Runbook: PostgreSQL Failure

## Target
- RTO: 30 minutes
- RPO: 5 minutes

## Symptoms
- API returns HTTP 500
- DB connection errors in `smdg` logs
- `pg_isready` fails

## Diagnosis
```bash
docker compose ps db
docker compose logs db --tail=100
docker compose exec -T db pg_isready -U smdg_user
docker compose exec -T db df -h
```

## Recovery Levels

### Level 1: Restart DB
```bash
docker compose restart db
sleep 10
docker compose exec -T db pg_isready -U smdg_user
curl -f http://localhost:8000/health/ready
```

### Level 2: Restore DB from backup
```bash
docker compose stop smdg
docker compose up -d db
gunzip -c /backups/smdg/db_<TIMESTAMP>.sql.gz | docker compose exec -T db psql -U smdg_user -d smdg
docker compose start smdg
```

### Level 3: Full platform restore
```bash
./scripts/restore.sh /backups/smdg/manifest_latest.txt
```

## Escalation
- If not recovered in 30 minutes: engage Database Specialist and Incident Commander.
