# Load Testing Guide (k6)

## Quick start

1. Generate test data:
   - `python scripts/generate_test_data.py`
2. Run smoke test:
   - `k6 run scripts/load-tests/smoke-tests/smoke.js`
3. Run API load test:
   - `k6 run scripts/load-tests/scenarios/api-load.js`

## Scenarios

- API load (`1000 rps target`): `scripts/load-tests/scenarios/api-load.js`
- File uploads (`100 parallel 1MB`): `scripts/load-tests/scenarios/upload-load.js`
- DICOM rendering (`50 parallel`): `scripts/load-tests/scenarios/dicom-load.js`
- Authentication (`500 login rps`): `scripts/load-tests/scenarios/auth-load.js`
- Mixed load (`80% read / 20% write`): `scripts/load-tests/scenarios/mixed-load.js`
- Stress test (progressive ramp-up): `scripts/load-tests/scenarios/stress-test.js`
- Soak test (`1 hour`): `scripts/load-tests/smoke-tests/soak.js`

## Docker-based execution

- Start full load-testing stack:
  - `docker compose -f docker-compose.load-test.yml up`
- Run one scenario:
  - `make load-test-api`
  - `make load-test-upload`
  - `make load-test-dicom`
  - `make load-test-auth`
  - `make load-test-mixed`
  - `make load-test-stress`
  - `make load-test-soak`

## Result analysis

- JSON summaries are exported to `load-test-results/`.
- Open key files:
  - `load-test-results/api-load-summary.json`
  - `load-test-results/upload-load-summary.json`
  - `load-test-results/dicom-load-summary.json`
  - `load-test-results/auth-load-summary.json`
  - `load-test-results/mixed-load-summary.json`
  - `load-test-results/stress-test-summary.json`
  - `load-test-results/soak-summary.json`
- Check p95, p99, and error rates against SLO thresholds in `scripts/load-tests/config/config.js`.

## Auth test modes

- `AUTH_TEST_MODE=capacity`:
  - Valid credentials are expected.
  - `401`/`5xx` are treated as errors.
  - Used to find login endpoint throughput limits.
- `AUTH_TEST_MODE=policy`:
  - Rate-limit policy behavior is expected.
  - `429` is tracked separately and allowed by policy thresholds.
  - Used to validate limiter protection, not max throughput.

## Pre-prod profile toggle

- `LOAD_TEST_MODE=true` enables pre-production load profile behavior (higher safe defaults for rate limits and load-oriented runtime knobs).
- Recommended startup for pre-prod checks:
  - `docker compose -f docker-compose.yml -f docker-compose.intl.yml up -d --build smdg`

## Known baseline (single instance)

Measured on one SMDG instance (`AUTH_TEST_MODE=capacity`, valid `ADMIN_USER`/`ADMIN_PASSWORD`):

- `AUTH_RPS=2`: stable, `error_rate=0`, `503_count=0`
- `AUTH_RPS=3`: stable, `error_rate=0`, `503_count=0`
- `AUTH_RPS=4`: degradation starts, `503_count=344/1201`, `error_rate=0.2864`
- `AUTH_RPS=5`: overload zone, `503_count=898/1501`, `error_rate=0.5983`

Operational interpretation:

- Safe ceiling (single instance): `3 login RPS`
- Warning zone: `4 login RPS`
- Overload zone: `>=5 login RPS`
