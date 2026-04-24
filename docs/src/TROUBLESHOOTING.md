# TROUBLESHOOTING.md

**Secure Medical Data Gateway (SMDG)** — troubleshooting guide

**Version:** 1.0
**Date:** 2026-04-05

---

## 1. Collecting diagnostics quickly

Before hunting for a root cause, run these commands:

```bash
# 1.1 Logs from every service
docker compose logs -f --tail=100

# 1.2 Logs of the main application only
docker compose logs smdg --tail=200

# 1.3 Status of all containers
docker compose ps -a

# 1.4 Health check
curl -I http://localhost/health
```

## 2. Common problems and solutions

### 2.1 Docker / the stack will not start

**Error:** `ports are already allocated`
**Fix:**

```bash
docker compose down
docker compose up -d
```

**Error:** `secret file not found`
**Fix:** make sure the `secrets/` folder exists and contains all files:

- `jwt_secret.txt`
- `admin_password.txt`
- `postgres_password.txt`
- `age.key`
- `grafana_password.txt`

**Error:** `permission denied` on startup
**Fix:**

```bash
chmod 600 secrets/*
chmod +x entrypoint.sh
```

### 2.2 PostgreSQL will not start

Symptom: the `db` container is stuck in `restarting` or `exited`.
Fix:

```bash
docker compose logs db
```

The most common cause is a missing `postgres_password` secret. Re-create it:

```bash
echo "<your-postgres-password>" > secrets/postgres_password.txt
docker compose down
docker compose up -d db
```

### 2.3 Redis unavailable / rate limiter broken

Symptom: `Redis connection failed` or `429 Too Many Requests`.
Fix:

```bash
docker compose logs redis
docker compose restart redis
```

### 2.4 ClamAV not responding

Symptom: uploading a file produces "Antivirus service is temporarily unavailable".
Fix:

```bash
docker compose logs clamav
docker compose restart clamav
```

ClamAV may take some time on first start (virus signature update).

### 2.5 Problems with the `age` key

**Error:** `age.key not found` or "public key is not initialised".
Fix:

```bash
mkdir -p secrets keys
age-keygen -o secrets/age.key
cp secrets/age.key keys/age.key
chmod 600 keys/age.key secrets/age.key

docker compose restart smdg
```

**Key rotation errors:** run the rotation manually:

```bash
docker compose exec smdg python -m app.cli rotate-keys
```

### 2.6 Authentication / login issues

Login does not work:

- Make sure `JWT_SECRET_KEY` is long and random
- Clear old cookies in the browser
- Check the logs: `docker compose logs smdg | grep -i auth`

2FA does not work:

- Scan the QR code inside an authenticator app
- Changing the password automatically resets 2FA

### 2.7 Files do not upload

**Error 413 (Payload Too Large):** raise `MAX_UPLOAD_SIZE_MB` in `.env` and restart.
**ClamAV blocks the file:** inspect ClamAV logs.
**File is not encrypted:** check the presence and permissions of `keys/age.key`.

### 2.8 Production mode issues

**Error:** `DEV_MODE=true` in production.
Fix: make sure `DEV_MODE=false` is set in `.env.prod`.

**Nginx returns 502 Bad Gateway:**

```bash
docker compose logs nginx
docker compose logs smdg
```

## 3. Useful commands

```bash
# Restart the application only
docker compose restart smdg

# Full logs with timestamps
docker compose logs -f -t smdg

# Exec into the application container
docker compose exec smdg bash

# Check database migrations
docker compose exec smdg alembic current

# Force cleanup of temporary files
docker compose exec smdg python -m app.cli cleanup-force
```

## 4. Where to find logs

- Application: `docker compose logs smdg`
- Audit: `audit_logs/` (files `audit_YYYY-MM-DD.log` and `audit.csv`)
- PostgreSQL: `docker compose logs db`
- Redis: `docker compose logs redis`
- ClamAV: `docker compose logs clamav`

If the issue is not resolved, open an Issue and attach:

- Output of `docker compose ps -a`
- The last 100 lines of `docker compose logs smdg --tail=100`
- A description of the steps that led to the error

## 5. One-click runbook navigation

Use these playbooks for fast incident response:

| Symptom | Runbook |
|---|---|
| API unavailable / high latency | [`docs/runbooks/components/smdg-api.md`](../runbooks/components/smdg-api.md) |
| PostgreSQL errors / slow queries | [`docs/runbooks/components/smdg-database.md`](../runbooks/components/smdg-database.md) |
| Redis issues / rate limiter anomalies | [`docs/runbooks/components/smdg-redis.md`](../runbooks/components/smdg-redis.md) |
| Upload/download storage failures | [`docs/runbooks/components/smdg-storage.md`](../runbooks/components/smdg-storage.md) |
| DICOM rendering/viewer issues | [`docs/runbooks/components/smdg-dicom.md`](../runbooks/components/smdg-dicom.md) |
| Auth / login / 401/403/429 issues | [`docs/runbooks/components/smdg-auth.md`](../runbooks/components/smdg-auth.md) |
| Audit inconsistencies | [`docs/runbooks/components/smdg-audit.md`](../runbooks/components/smdg-audit.md) |
| Webhook backlog / failures | [`docs/runbooks/components/smdg-webhooks.md`](../runbooks/components/smdg-webhooks.md) |

Priority incident playbooks:

- High CPU: [`docs/runbooks/incidents/high-cpu.md`](../runbooks/incidents/high-cpu.md)
- High memory: [`docs/runbooks/incidents/high-memory.md`](../runbooks/incidents/high-memory.md)
- DB connection saturation: [`docs/runbooks/incidents/db-connection-limit.md`](../runbooks/incidents/db-connection-limit.md)
- Disk full: [`docs/runbooks/incidents/disk-full.md`](../runbooks/incidents/disk-full.md)
- DICOM slow: [`docs/runbooks/incidents/dicom-slow.md`](../runbooks/incidents/dicom-slow.md)
- Auth failure: [`docs/runbooks/incidents/auth-failure.md`](../runbooks/incidents/auth-failure.md)
- Audit gap: [`docs/runbooks/incidents/audit-gap.md`](../runbooks/incidents/audit-gap.md)
