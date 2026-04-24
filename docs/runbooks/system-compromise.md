# Runbook: System Compromise

## Target
- RTO: 2 hours
- RPO: N/A

## Symptoms
- Unauthorized access evidence
- IOC alerts from monitoring
- Credential misuse signs

## Immediate Containment
```bash
docker compose stop smdg
docker compose stop nginx
# Block external traffic at firewall/LB immediately
```

## Recovery Steps
```bash
# 1) Preserve forensic evidence (logs, snapshots)
# 2) Rotate secrets, tokens, and encryption keys
# 3) Rebuild from trusted images and known-good backup
./scripts/restore.sh /backups/smdg/manifest_latest.txt
```

## Post-Recovery
- Run full security audit
- Notify stakeholders/security team
- Publish incident report and corrective actions
