# Testing

> **Translation status:** English stub. The authoritative Russian
> testing document is [`docs/locales/ru/TESTING.md`](../locales/ru/TESTING.md).

## Test stack

- `pytest` with `pytest-asyncio` for unit and integration tests.
- `httpx.AsyncClient` for FastAPI endpoint tests.
- `pytest-cov` for coverage.
- `faker` for test data generation.
- `testcontainers-python` (optional) for ephemeral PostgreSQL / Redis.

## Layout

```
tests/
├── conftest.py
├── api/             # endpoint tests
├── core/            # unit tests for core modules
├── crypto/          # age encryption tests
├── models/          # SQLModel tests
└── integration/     # end-to-end scenarios
```

## Running tests

```bash
pytest                          # full suite
pytest -k "auth"                # only auth-related tests
pytest --cov=app --cov-report=html
```

## Writing tests

- Always include a docstring describing the scenario.
- Use fixtures from `conftest.py` for the async session and HTTP
  client.
- Audit assertions should verify English strings (audit logs are
  English-only per the language policy).
- When asserting on UI-facing error messages, use the stable `code`
  field from the API response rather than the English `detail` text.

## CI

GitHub Actions runs `pytest` on every push and pull request. The
coverage gate is 80 %. See `.github/workflows/ci.yml`.
