# Runbook: Docker/Orchestrator Failure

## Target
- RTO: 30 minutes
- RPO: 0

## Symptoms
- `docker compose` commands fail
- Docker daemon unavailable
- Unexpected service scheduling/restart behavior

## Diagnosis
```bash
docker info
docker compose ps
```

## Recovery
```bash
sudo systemctl restart docker
sleep 10
docker compose up -d
docker compose ps
curl -f http://localhost:8000/health/ready
```

## Escalation
- If daemon remains unstable, fail over to standby host.
