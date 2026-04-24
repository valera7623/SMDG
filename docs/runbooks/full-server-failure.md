# Runbook: Full Server Failure

## Target
- RTO: 4 hours
- RPO: 1 hour

## Symptoms
- Host unavailable
- All containers down
- No SSH/API reachability

## Recovery
```bash
# On new host
git clone <repo_url> smdg
cd smdg

# Restore required secrets and key materials
# .env, secrets/, keys/

./scripts/restore.sh /backups/smdg/manifest_latest.txt
curl -f http://localhost:8000/health/ready
```

## Escalation
- If infra restoration exceeds 4 hours, invoke BCP fallback environment.
