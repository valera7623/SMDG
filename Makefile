.PHONY: load-test-smoke load-test-api load-test-upload load-test-dicom load-test-auth load-test-mixed load-test-stress load-test-soak load-test-all load-test-dashboard load-test-clean test-compression security-scan-local

# Local security: writes reports/bandit-report.json, semgrep-report.json, gitleaks-report.json, trivy-report.json, api-security-report.xml, security-report.html
security-scan-local:
	./scripts/run_local_security_scans.sh

load-test-smoke:
	docker compose -f docker-compose.load-test.yml run --rm k6 run /scripts/smoke-tests/smoke.js --summary-export=/results/smoke-summary.json

load-test-api:
	docker compose -f docker-compose.load-test.yml run --rm k6 run /scripts/scenarios/api-load.js --summary-export=/results/api-load-summary.json

load-test-upload:
	docker compose -f docker-compose.load-test.yml run --rm k6 run /scripts/scenarios/upload-load.js --summary-export=/results/upload-load-summary.json

load-test-dicom:
	docker compose -f docker-compose.load-test.yml run --rm k6 run /scripts/scenarios/dicom-load.js --summary-export=/results/dicom-load-summary.json

load-test-auth:
	docker compose -f docker-compose.load-test.yml run --rm k6 run /scripts/scenarios/auth-load.js --summary-export=/results/auth-load-summary.json

load-test-mixed:
	docker compose -f docker-compose.load-test.yml run --rm k6 run /scripts/scenarios/mixed-load.js --summary-export=/results/mixed-load-summary.json

load-test-stress:
	docker compose -f docker-compose.load-test.yml run --rm k6 run /scripts/scenarios/stress-test.js --summary-export=/results/stress-test-summary.json

load-test-soak:
	docker compose -f docker-compose.load-test.yml run --rm k6 run /scripts/smoke-tests/soak.js --summary-export=/results/soak-summary.json

load-test-all: load-test-smoke load-test-api load-test-upload load-test-auth load-test-mixed load-test-dicom load-test-stress

load-test-dashboard:
	docker compose -f docker-compose.load-test.yml up -d influxdb grafana k6-dashboard

load-test-clean:
	docker compose -f docker-compose.load-test.yml down -v
	rm -rf load-test-results/*

test-compression:
	poetry run pytest -o addopts='' tests/test_compression.py -v
