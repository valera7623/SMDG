#!/usr/bin/env bash
# Run security scanners and write JSON/XML artifacts under reports/, then build HTML summary.
# Prerequisites: bandit, semgrep, gitleaks, trivy; poetry (recommended) for pytest deps; Docker image smdg:latest for Trivy (step 0).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
mkdir -p reports

echo "== 0. Docker image for Trivy (optional, skip if smdg:latest exists) =="
if ! docker image inspect smdg:latest >/dev/null 2>&1; then
  echo "Building smdg:latest ..."
  docker build -t smdg:latest .
else
  echo "Using existing smdg:latest"
fi

echo "== 1. Bandit =="
# Older Bandit builds may not support --exit-zero; always write JSON and continue.
bandit -c .bandit.yaml -r app/ -f json -o reports/bandit-report.json || true

echo "== 2. Semgrep =="
semgrep --config .semgrep.yml --json --output reports/semgrep-report.json || true

echo "== 3. Gitleaks =="
# Working tree only: historic commits may still contain rotated material until history is rewritten.
gitleaks detect --source . --config .gitleaks.toml --no-git --report-format json --report-path reports/gitleaks-report.json || true

echo "== 4. Trivy (image) =="
trivy image smdg:latest --severity HIGH,CRITICAL --format json --output reports/trivy-report.json --exit-code 0 || true

echo "== 5. API security tests =="
if command -v poetry >/dev/null 2>&1; then
  poetry run pytest tests/security/test_api_security.py -v --junitxml=reports/api-security-report.xml || true
else
  echo "WARN: poetry not found; using python3 -m pytest (install project deps first: pip install python-dotenv ... or poetry install)"
  python3 -m pytest tests/security/test_api_security.py -v --junitxml=reports/api-security-report.xml || true
fi

echo "== 6. Consolidated HTML report =="
python3 scripts/generate_security_report.py --input reports --output reports/security-report.html --mode balanced

echo "Done. Artifacts: reports/*.json, reports/api-security-report.xml, reports/security-report.html"
