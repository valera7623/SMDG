# Runbook: Single Container Failure

## Target
- RTO: 5 minutes
- RPO: 0

## Symptoms
- One service in `Exited` or `unhealthy`
- Endpoint degradation tied to one component

## Diagnosis
```bash
docker compose ps
docker compose logs <service> --tail=100
```

## Recovery
```bash
docker compose restart <service>
sleep 10
docker compose ps
curl -f http://localhost:8000/health/ready
```

## Escalation
- If repeated crash loop persists after 3 restarts, escalate to Platform Engineer.
