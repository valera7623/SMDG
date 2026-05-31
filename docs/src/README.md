# Secure Medical Data Gateway (SMDG)

**Secure transfer of medical files with end-to-end encryption**

**Current version:** **4.0.0** (core and DICOM Viewer); audit export — **3.1.0**.

SMDG is a self-hosted solution for secure exchange of medical data between doctors, clinics and patients.
All files are encrypted on the server, protected by time-limited links and logged in a full audit trail.

Detailed guides live under **[docs/](./)** — see the table in the "Documentation" section below.

---

## Features

### Core (v1.0)

- End-to-end file encryption with **age**
- File type validation (MIME and extension checks) before encryption
- **JWT** + HttpOnly cookies
- Two-factor authentication (**TOTP** / 2FA)
- Role-based access control (**RBAC**): `admin` | `doctor` | `user` | `super_admin` (multi-tenant)
- **Rate limiting** (slowapi + **Redis**)
- Full operations **audit** (**JSON** per day + **CSV** with rotation)
- **Audit export** for administrators: **Excel**, **PDF**, **CSV** over a period with filters ([API](API_GUIDE.md#11-audit-export-api))
- Convenient web UI + admin panel
- Automatic cleanup of old files and encryption key rotation
- **Docker** + **Docker Secrets**

### Storage (v2.0)

- **StorageBackend** abstraction: **LocalStorageBackend** and **S3StorageBackend**
- S3-compatible providers: **MinIO**, **Yandex Object Storage**, **Selectel**, **AWS S3**, **DigitalOcean Spaces**
- **S3 Lifecycle Policies** (auto-deletion based on TTL rules)
- FS → S3 migration script (`scripts/migrate_to_s3.py`)

### Webhooks (v2.1)

- Events: `file.uploaded`, `file.downloaded`, `file.deleted`
- Payload signed with **HMAC-SHA256**, retries with **exponential backoff**
- Delivery history and statuses persisted in the database

### DICOM Viewer (v3.0)

- Server-side rendering with **pydicom** + **numpy** + **PIL** → PNG
- Multi-frame (**CT/MRI**) with **Cine** mode
- **Window/Level** presets (Bone, Lung, Brain, Abdomen, Liver)
- Measurements: ruler, angle, ROI (rectangle / ellipse)
- Export PNG / screenshots with annotations
- **DICOMweb**: **QIDO-RS** + **WADO-RS**
- **OHIF**-style viewer integration
- **Redis**: metadata and PNG caching

See [DICOM_VIEWER.md](DICOM_VIEWER.md) for details.

---

## Minimum requirements

**For development and running locally:**

| Requirement           | Minimum                      | Recommended             |
|-----------------------|------------------------------|-------------------------|
| Docker + Compose      | Docker 24+, Compose v2       | Docker Desktop 4.20+    |
| Python                | 3.10+                        | 3.12.x                  |
| RAM                   | 4 GB                         | 8 GB+                   |
| CPU                   | 2 cores                      | 4+ cores                |
| Disk                  | 10 GB free                   | 20 GB+ (SSD)            |
| OS                    | Linux / macOS / Windows+WSL2 | Ubuntu 22.04 / 24.04    |

**For production:** PostgreSQL 15+, Redis 7+, 8 GB+ RAM.

---

## Quick start

### Local (Development)

```bash
git clone <your-repo>
cd smdg

cp .env.example .env
docker compose up --build
```

Application: **https://localhost** (or the HTTP port defined in compose).

### Production

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

### Running with MinIO (S3)

```bash
# In .env:
S3_ENABLED=true
S3_ACCESS_KEY=minioadmin
S3_SECRET_KEY=minioadmin123

docker compose --profile s3 up -d
```

MinIO console: http://localhost:9001

### Migrating data FS → S3

```bash
python scripts/migrate_to_s3.py --dry-run
python scripts/migrate_to_s3.py --delete-local
```

---

## Deployment profiles (feature flags)

One codebase supports several profiles via **`DEPLOYMENT_TYPE`** (`russia` | `intl` | `single` | `saas` | `demo`): the feature matrix lives in `app/core/feature_flags.py`, runtime checks under `GET /health/features` and CLI `python -m app.cli feature-info`.

| Profile  | Summary                                                                                             |
|----------|-----------------------------------------------------------------------------------------------------|
| `russia` | Russian data-protection law (FZ-152): local storage, DICOM, mandatory 2FA, 3-year audit, GOST-ready |
| `intl`   | S3/MinIO, DICOM, GDPR/HIPAA-oriented features, 2FA                                                  |
| `single` | Single tenant, simplified admin, DICOM, 2FA, local disk by default                                  |
| `saas`   | Multi-tenant, billing/white-label in matrix, object storage, DICOM, 2FA                             |
| `demo`   | Public showcase: local storage, optional 2FA, DICOM, GDPR/HIPAA features, small upload cap, 24h data reset |

See [DEPLOYMENT.md](DEPLOYMENT.md) and the full feature list in [FEATURES.md](FEATURES.md).

---

## Project layout

```
smdg/
├── app/
│   ├── api/                    # REST: upload, download, auth, admin, webhooks, dicom,
│   │                           # admin_audit_export
│   ├── core/                   # config, DB, security, storage_backend, audit, audit_export
│   ├── crypto/                 # age: encryption / key rotation
│   ├── models/                 # SQLModel: User, File, FileLink, Tenant, Webhook, DICOM …
│   └── main.py                 # FastAPI, lifespan, middleware
├── static/                     # HTML, JS, CSS (frontend)
├── audit_logs/                 # JSON audit_YYYY-MM-DD.log + CSV (see AUDIT_LOGS_DIR)
├── encrypted/
├── decrypted/
├── keys/
├── migrations/
├── tests/
├── docs/                       # Architecture, API, deployment, DICOM, SECURITY …
├── docker-compose.yml
├── docker-compose.prod.yml
├── Dockerfile
├── entrypoint.sh
├── pyproject.toml
└── README.md
```

| File                            | Purpose                               |
|---------------------------------|---------------------------------------|
| `app/main.py`                   | Lifespan, middleware, routers         |
| `app/core/config.py`            | Settings (Pydantic Settings)          |
| `app/core/audit_export.py`      | Log reading, Excel/PDF/CSV export     |
| `app/api/admin_audit_export.py` | `GET /api/admin/audit/export`         |
| `app/core/storage_backend.py`   | Local / S3                            |
| `scripts/migrate_to_s3.py`      | Migration into object storage         |

---

## Security and compliance

- Encryption with **age**, passwords hashed with **Argon2**, JWT stored in **HttpOnly** cookies
- Policy: [SECURITY.md](SECURITY.md)
- Compliance template (FZ-152 / GDPR): [COMPLIANCE_TEMPLATE.md](COMPLIANCE_TEMPLATE.md)

---

## Documentation

| Document                                     | Description                                         |
|----------------------------------------------|-----------------------------------------------------|
| [API_GUIDE.md](API_GUIDE.md)                 | API: authentication, limits, DICOM, audit export    |
| [ARCHITECTURE.md](ARCHITECTURE.md)           | Architecture, ERD, diagrams                         |
| [DEPLOYMENT.md](DEPLOYMENT.md)               | Deployment, audit export dependencies               |
| [DICOM_VIEWER.md](DICOM_VIEWER.md)           | DICOM Viewer                                        |
| [MULTI_TENANCY.md](MULTI_TENANCY.md)         | Multi-tenancy                                       |
| [CHANGELOG.md](CHANGELOG.md)                 | Version history                                     |
| [SECURITY.md](SECURITY.md)                   | Security policy                                     |
| [TESTING.md](TESTING.md)                     | Testing strategy                                    |
| [CONTRIBUTING.md](CONTRIBUTING.md)           | Contribution guide                                  |
| [COMPLIANCE_TEMPLATE.md](COMPLIANCE_TEMPLATE.md) | FZ-152 / GDPR compliance template               |

---

## Interfaces

| Interface  | URL        |
|------------|------------|
| Web UI     | `/`        |
| Admin      | `/admin`   |
| Swagger    | `/docs`    |
| Health     | `/health`  |
| Metrics    | `/metrics` |

---

## License

MIT. Author: Valeriy Popov.

SMDG — your secure gateway for medical data.
