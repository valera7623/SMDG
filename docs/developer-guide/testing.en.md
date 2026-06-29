# Testing

SMDG testing strategy.

## Run tests

```bash
poetry install
poetry run pytest
```

With coverage:

```bash
poetry run pytest --cov=app --cov-report=term-missing
```

## Layout

```
tests/
├── test_api/          # HTTP endpoints (httpx ASGI)
├── test_core/         # storage, rate limiter, audit
├── test_crypto/       # age encryption
└── conftest.py        # fixtures (DB, client)
```

## CI

Workflow: `.github/workflows/ci.yml`

- Python 3.10, 3.11, 3.12
- pytest + coverage
- ruff, bandit, gitleaks

## Load testing

k6 scenarios in `scripts/load-tests/`:

```bash
docker compose -f docker-compose.load-test.yml up
```

See [load-testing.md](../load-testing.md).

## Security scans

```bash
./scripts/run_local_security_scans.sh
```

## Local development

```bash
cp .env.example .env
docker compose up -d db redis
poetry run pytest tests/test_api/test_health.py -v
```

See [src/TESTING.md](../src/TESTING.md).
