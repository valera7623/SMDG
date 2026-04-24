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
