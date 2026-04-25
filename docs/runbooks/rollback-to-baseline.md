# Rollback to baseline stack

Use this runbook when you need to leave the horizontal scaling topology
(`docker-compose.scale.yml`) and return to the default local stack.

## Prerequisites

- You are in the repository root.
- Docker daemon is running.

## Steps

```bash
# 1) Stop and remove the scaled project
docker compose -p smdg-scale -f docker-compose.scale.yml down -v

# 2) Ensure default upstream target for local nginx
# nginx/upstream-target.conf must contain:
# map $request_uri $smdg_upstream { default http://smdg:8000; }

# 3) Start the baseline stack
docker compose up -d

# 4) Verify readiness
curl -k https://localhost/health/ready
```

## If UI returns 502

```bash
docker compose restart nginx
curl -k https://localhost/health/ready
```

If `ready=true` is returned, reload the browser page.
