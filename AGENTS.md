# AGENTS.md

## Cursor Cloud specific instructions

### Product

**SMDG** (Secure Medical Data Gateway) — async FastAPI backend, static HTML/JS frontend, PostgreSQL, Redis, `age` encryption. See `README.md` and `docs/src/`.

### Services (local dev without full Docker)

| Service | Purpose |
|---------|---------|
| PostgreSQL 15+ | App DB (`smdg` or `smdg_test`) |
| Redis 7 | Sessions, cache, rate limits |
| `age` / `age-keygen` | Crypto tests and file encryption |

This VM has no systemd: start data stores with `sudo service postgresql start` and `sudo service redis-server start` (or `redis-server --daemonize yes`).

### One-time host setup (not in update script)

- OS packages: `postgresql`, `redis-server`, `age`
- DB role/db (match `.env.test`): user `smdg_user` / password `password`, databases `smdg` and `smdg_test`
- Poetry: https://install.python-poetry.org — add `~/.local/bin` to `PATH`
- Test dirs + age keys: paths under `/tmp/smdg_test/` per `.env.test` (see `PRIVATE_KEY_PATH` / `PUBLIC_KEY_PATH`)
- Migrations: `set -a && source .env.test && set +a && poetry run alembic upgrade head`

### Running the API (dev)

```bash
export PATH="$HOME/.local/bin:$PATH"
set -a && source .env.test && set +a
poetry run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

- Health: `GET http://127.0.0.1:8000/health`
- OpenAPI: `http://127.0.0.1:8000/docs`
- UI: `http://127.0.0.1:8000/` — first dev admin is created on startup (`DEV_MODE=true`): **admin** / **admin123** (not the `ADMIN_PASSWORD` from `.env.test` unless you seed via Docker/CLI).

Login API uses **form** fields (`username`, `password`), not JSON.

### Lint / test (see also `.github/workflows/ci.yml`)

```bash
poetry run ruff check app/lifecycle app/bootstrap app/core/version.py app/main.py
poetry run pytest tests/ -v --cov=app --cov-fail-under=80
```

Load env from `.env.test` before pytest (conftest loads it automatically).

### Gotcha: database after pytest

The suite can leave `smdg_test` at Alembic head **without** application tables. If Uvicorn fails with `relation "tenants" does not exist`, recreate the DB and re-run migrations:

```bash
sudo -u postgres psql -c "DROP DATABASE IF EXISTS smdg_test; CREATE DATABASE smdg_test OWNER smdg_user;"
set -a && source .env.test && set +a && poetry run alembic upgrade head
```

### Full stack (optional)

Docker Compose (`docker-compose.yml` or lean `docker-compose.demo.yml`) needs Docker, `./scripts/vps-bootstrap-secrets.sh`, and often `./generate_cert.sh` for HTTPS via nginx. Quick start: `README.md`.
