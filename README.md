**English** | [Русский](README.ru.md) | [Deutsch](README.de.md) | [Français](README.fr.md)

# SMDG — Secure Medical Data Gateway

**Self-hosted, end-to-end encrypted medical file exchange.**

Version: **4.0.0** (core and DICOM Viewer) · audit export: **3.1.0**.

SMDG lets doctors, clinics and patients exchange medical files safely.
Every file is encrypted server-side with [age](https://age-encryption.org/),
protected by time-limited one-shot links, scanned by ClamAV and logged in
a full audit trail. A built-in DICOM viewer renders studies in the browser
without shipping decrypted data to the client.

## Documentation

Full user- and operator-facing documentation lives in
[`docs/`](docs/README.md). The English source of truth sits under
[`docs/src/`](docs/src/), with translations under
[`docs/locales/{ru,de,fr}/`](docs/locales/).

- Overview — [`docs/src/README.md`](docs/src/README.md)
- API guide — [`docs/src/API_GUIDE.md`](docs/src/API_GUIDE.md)
- Architecture — [`docs/src/ARCHITECTURE.md`](docs/src/ARCHITECTURE.md)
- Deployment profiles — [`docs/src/DEPLOYMENT.md`](docs/src/DEPLOYMENT.md)
- Horizontal scaling runbook — [`docs/src/DEPLOYMENT.md`](docs/src/DEPLOYMENT.md#horizontal-scaling-stateless-cluster)
- Rollback to baseline runbook — [`docs/runbooks/rollback-to-baseline.md`](docs/runbooks/rollback-to-baseline.md)
- DICOM Viewer — [`docs/src/DICOM_VIEWER.md`](docs/src/DICOM_VIEWER.md)
- Security policy — [`docs/src/SECURITY.md`](docs/src/SECURITY.md)

## Quick start

```bash
git clone <your-repo>
cd smdg
cp .env.example .env
docker compose up --build
```

Open <https://localhost>. Default dev credentials: `admin` / `admin`
(change them immediately).

## Deployment profiles

The environment variable `DEPLOYMENT_TYPE` selects the feature matrix:

| Profile  | Summary                                                         |
|----------|-----------------------------------------------------------------|
| `russia` | FZ-152 compliant: local storage, mandatory 2FA, 3-year audit    |
| `intl`   | S3/MinIO, DICOM, GDPR/HIPAA-oriented features                   |
| `single` | Single tenant, simplified admin, local disk by default          |
| `saas`   | Multi-tenant, billing/white-label, object storage               |

See [`docs/src/DEPLOYMENT.md`](docs/src/DEPLOYMENT.md) for details.

For stateless horizontal scaling (Redis-backed sessions/cache/queue, Nginx load
balancer, health/readiness checks, blue/green cutover scripts), use the section
**"Horizontal scaling (stateless cluster)"** in the deployment guide.
Rollback procedure is documented in
[`docs/runbooks/rollback-to-baseline.md`](docs/runbooks/rollback-to-baseline.md).

## Multilingual support

- Web UI: English / Русский / Deutsch / Français with a runtime language
  switcher (see [`static/js/i18n.js`](static/js/i18n.js)).
- API documentation: `/docs` (English), `/docs/ru`, `/docs/de`, `/docs/fr`
  and `/openapi.{ru,de,fr}.json`.
- User documentation: `docs/src/` (English) + `docs/locales/<lang>/`.

## Security Scanning

The CI workflow [`security-scan.yml`](.github/workflows/security-scan.yml)
runs SAST, SCA, secrets, container and DAST checks on push, PR, schedule and
manual trigger.

### Required secrets matrix

| Secret | Required | Used by | Notes |
|---|---|---|---|
| `SNYK_TOKEN` | Optional (required for Snyk jobs) | `sca-snyk`, `sca-snyk-container` | If missing, Snyk jobs are skipped. |
| `SONAR_TOKEN` | Optional (required for SonarQube job) | `sast-sonarqube` | Must be paired with `SONAR_HOST_URL`. |
| `SONAR_HOST_URL` | Optional (required for SonarQube job) | `sast-sonarqube` | Example: `https://sonar.company.local`. |

### Mode auto-switching (`SECURITY_SCAN_MODE`)

The workflow auto-selects scan mode by event:

- `schedule` -> `audit`
- `push` / `pull_request` / `workflow_dispatch` -> `balanced` (default)
- override for non-scheduled events via repository variable
  `SECURITY_SCAN_MODE=strict` (or `balanced`)

Effective expression in workflow:

```yaml
env:
  SECURITY_SCAN_MODE: ${{ github.event_name == 'schedule' && 'audit' || (vars.SECURITY_SCAN_MODE == 'strict' && 'strict' || 'balanced') }}
```

How to set repository variable in GitHub:

1. Open repository -> **Settings** -> **Secrets and variables** -> **Actions**.
2. Go to **Variables** tab.
3. Click **New repository variable**.
4. Set:
   - Name: `SECURITY_SCAN_MODE`
   - Value: `strict` (or `balanced`)

GitHub CLI example:

```bash
gh variable set SECURITY_SCAN_MODE --body strict
```

### Fail policy (pipeline break conditions)

Current workflow policy is designed to always produce artifacts and summary, so
many scanners run with non-blocking mode (`|| true`) to keep full visibility.

| Stage | Tool | Pipeline fails on |
|---|---|---|
| SAST | Bandit | Blocking on findings and execution/runtime errors (non-zero exit). |
| SAST | Semgrep | Blocking on findings and execution/runtime errors (non-zero exit). |
| SAST | SonarQube | Sonar scan job failure (when enabled with secrets). |
| SCA | Safety | Blocking on findings and execution/runtime errors (non-zero exit). |
| SCA | Snyk (code) | Non-zero exit from Snyk test action (policy is managed in Snyk org/project). |
| SCA | Snyk (container) | Non-zero exit from Snyk docker action (policy is managed in Snyk org/project). |
| Secrets | Gitleaks | Blocking on leaked secrets and execution/runtime errors (non-zero exit). |
| Secrets | TruffleHog | Blocking on findings and execution/runtime errors (non-zero exit). |
| Container | Trivy | Blocking on `CRITICAL` vulnerabilities (`exit-code: 1`, `ignore-unfixed: true`). |
| Container | Grype | Blocking on `high`+ vulnerabilities (`fail-build: true`, `severity-cutoff: high`). |
| DAST | OWASP ZAP | ZAP action failure. |
| DAST | Nuclei | Nuclei action failure. |
| DAST | API security tests | Pytest test failures are blocking. |

Production hardening is enabled in the current workflow. If you want a stricter
gate, increase Trivy threshold from `CRITICAL` to `HIGH,CRITICAL`.

### Policy toggles

Use these snippets as ready-to-copy switches for
`.github/workflows/security-scan.yml`.

**Strict mode (recommended for protected branches)**

```yaml
# Semgrep: fail on findings
- name: Save Semgrep JSON report
  run: semgrep --config .semgrep.yml --json --output semgrep-report.json

# Trivy: fail on HIGH + CRITICAL
- name: Run Trivy scanner
  uses: aquasecurity/trivy-action@master
  with:
    image-ref: smdg:latest
    format: sarif
    output: trivy-report.sarif
    severity: HIGH,CRITICAL
    exit-code: "1"
    ignore-unfixed: false

# Grype: fail on medium+
- name: Run Grype scanner
  uses: anchore/scan-action@v3
  with:
    image: smdg:latest
    fail-build: true
    severity-cutoff: medium
    output-format: json
    output-file: grype-report.json
```

**Balanced mode (fewer false positives for fast delivery)**

```yaml
# Semgrep: fail only on ERROR severity
- name: Save Semgrep JSON report
  run: semgrep --config .semgrep.yml --severity ERROR --json --output semgrep-report.json

# Trivy: fail on CRITICAL only
- name: Run Trivy scanner
  uses: aquasecurity/trivy-action@master
  with:
    image-ref: smdg:latest
    format: sarif
    output: trivy-report.sarif
    severity: CRITICAL
    exit-code: "1"
    ignore-unfixed: true

# Grype: fail on high+
- name: Run Grype scanner
  uses: anchore/scan-action@v3
  with:
    image: smdg:latest
    fail-build: true
    severity-cutoff: high
    output-format: json
    output-file: grype-report.json
```

**Audit mode (nightly/scheduled, non-blocking artifacts only)**

```yaml
# Semgrep: do not fail pipeline
- name: Save Semgrep JSON report
  run: semgrep --config .semgrep.yml --json --output semgrep-report.json || true

# Bandit / Safety / Gitleaks / TruffleHog: non-blocking scan runs
- name: Run Bandit
  run: bandit -c .bandit.yaml -r app/ -f json -o bandit-report.json || true

- name: Run Safety
  run: safety check -r requirements.txt --json > safety-report.json || true

- name: Run Gitleaks
  run: |
    docker run --rm -v "$PWD:/repo" zricethezav/gitleaks:latest detect \
      --source /repo \
      --config /repo/.gitleaks.toml \
      --report-format json \
      --report-path /repo/gitleaks-report.json || true

- name: Run TruffleHog
  run: |
    docker run --rm -v "$PWD:/pwd" trufflesecurity/trufflehog:latest filesystem /pwd \
      --json > trufflehog-report.json || true

# Trivy / Grype: report-only mode
- name: Run Trivy scanner
  uses: aquasecurity/trivy-action@master
  with:
    image-ref: smdg:latest
    format: sarif
    output: trivy-report.sarif
    severity: HIGH,CRITICAL
    exit-code: "0"
    ignore-unfixed: true

- name: Run Grype scanner
  uses: anchore/scan-action@v3
  with:
    image: smdg:latest
    fail-build: false
    severity-cutoff: high
    output-format: json
    output-file: grype-report.json
```

## License

MIT. Author: Valeriy Popov.
