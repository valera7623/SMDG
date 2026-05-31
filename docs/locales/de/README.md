<!-- smdg-i18n-header-start
source: docs/src/README.md
source_sha1: 231cd132ac83d5971a90dcb1e979cea1ab468499
language: de
last_sync: 2026-05-31
status: translated
smdg-i18n-header-end -->

# Secure Medical Data Gateway (SMDG)

**Sichere Übertragung medizinischer Dateien mit Ende-zu-Ende-Verschlüsselung**

**Aktuelle Version:** **4.0.0** (Kern und DICOM Viewer); Audit-Export — **3.1.0**.

SMDG ist eine selbst gehostete Lösung für den sicheren Austausch medizinischer
Daten zwischen Ärzten, Kliniken und Patienten. Alle Dateien werden auf dem
Server verschlüsselt, durch zeitlich begrenzte Links geschützt und in einem
vollständigen Audit-Trail protokolliert.

Ausführliche Anleitungen befinden sich unter **[docs/](../../README.md)** —
siehe die Tabelle im Abschnitt „Dokumentation“ weiter unten.

---

## Funktionen

### Kern (v1.0)

- Ende-zu-Ende-Dateiverschlüsselung mit **age**
- Validierung des Dateityps (MIME- und Erweiterungsprüfung) vor der Verschlüsselung
- **JWT** + HttpOnly-Cookies
- Zwei-Faktor-Authentifizierung (**TOTP** / 2FA)
- Rollenbasierte Zugriffskontrolle (**RBAC**): `admin` | `doctor` | `user` | `super_admin` (mandantenfähig)
- **Ratenbegrenzung** (slowapi + **Redis**)
- Vollständiges Betriebs-**Audit** (**JSON** pro Tag + **CSV** mit Rotation)
- **Audit-Export** für Administratoren: **Excel**, **PDF**, **CSV** über einen Zeitraum mit Filtern ([API](API_GUIDE.md#audit-export-api))
- Komfortable Web-UI + Admin-Panel
- Automatische Bereinigung alter Dateien und Rotation der Verschlüsselungsschlüssel
- **Docker** + **Docker Secrets**

### Speicher (v2.0)

- **StorageBackend**-Abstraktion: **LocalStorageBackend** und **S3StorageBackend**
- S3-kompatible Anbieter: **MinIO**, **Yandex Object Storage**, **Selectel**, **AWS S3**, **DigitalOcean Spaces**
- **S3-Lifecycle-Policies** (automatisches Löschen anhand von TTL-Regeln)
- Migrationsskript FS → S3 (`scripts/migrate_to_s3.py`)

### Webhooks (v2.1)

- Ereignisse: `file.uploaded`, `file.downloaded`, `file.deleted`
- Nutzlast signiert mit **HMAC-SHA256**, Wiederholungen mit **exponentiellem Backoff**
- Zustellhistorie und -status in der Datenbank gespeichert

### DICOM Viewer (v3.0)

- Serverseitiges Rendering mit **pydicom** + **numpy** + **PIL** → PNG
- Multi-Frame (**CT/MRT**) mit **Cine**-Modus
- **Window/Level**-Voreinstellungen (Bone, Lung, Brain, Abdomen, Liver)
- Messungen: Lineal, Winkel, ROI (Rechteck / Ellipse)
- Export PNG / Screenshots mit Annotationen
- **DICOMweb**: **QIDO-RS** + **WADO-RS**
- Integration im **OHIF**-Stil
- **Redis**: Caching von Metadaten und PNG

Siehe [DICOM_VIEWER.md](DICOM_VIEWER.md) für Details.

---

## Mindestanforderungen

**Für Entwicklung und lokalen Betrieb:**

| Anforderung           | Minimum                      | Empfohlen               |
|-----------------------|------------------------------|-------------------------|
| Docker + Compose      | Docker 24+, Compose v2       | Docker Desktop 4.20+    |
| Python                | 3.10+                        | 3.12.x                  |
| RAM                   | 4 GB                         | 8 GB+                   |
| CPU                   | 2 Kerne                      | 4+ Kerne                |
| Festplatte            | 10 GB frei                   | 20 GB+ (SSD)            |
| Betriebssystem        | Linux / macOS / Windows+WSL2 | Ubuntu 22.04 / 24.04    |

**Für Produktion:** PostgreSQL 15+, Redis 7+, 8 GB+ RAM.

---

## Schnellstart

### Lokal (Entwicklung)

```bash
git clone <your-repo>
cd smdg

cp .env.example .env
docker compose up --build
```

Anwendung: **https://localhost** (oder der in Compose definierte HTTP-Port).

### Produktion

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

### Betrieb mit MinIO (S3)

```bash
# In .env:
S3_ENABLED=true
S3_ACCESS_KEY=minioadmin
S3_SECRET_KEY=minioadmin123

docker compose --profile s3 up -d
```

MinIO-Konsole: http://localhost:9001

### Datenmigration FS → S3

```bash
python scripts/migrate_to_s3.py --dry-run
python scripts/migrate_to_s3.py --delete-local
```

---

## Bereitstellungsprofile (Feature Flags)

Eine Codebasis unterstützt mehrere Profile über **`DEPLOYMENT_TYPE`**
(`russia` | `intl` | `single` | `saas` | `demo`): die Funktionsmatrix liegt in
`app/core/feature_flags.py`, Laufzeitprüfungen unter `GET /health/features` und
CLI `python -m app.cli feature-info`.

| Profil   | Zusammenfassung                                                                                     |
|----------|-----------------------------------------------------------------------------------------------------|
| `russia` | Russisches Datenschutzrecht (FZ-152): lokaler Speicher, DICOM, verpflichtende 2FA, 3 Jahre Audit, GOST-bereit |
| `intl`   | S3/MinIO, DICOM, DSGVO/HIPAA-orientierte Funktionen, 2FA                                            |
| `single` | Einzelner Tenant, vereinfachtes Admin, DICOM, 2FA, lokale Festplatte standardmäßig                  |
| `saas`   | Mandantenfähig, Abrechnung/White-Label in der Matrix, Objektspeicher, DICOM, 2FA                    |
| `demo`   | Öffentliche Vorführung: lokaler Speicher, optionale 2FA, DICOM, DSGVO/HIPAA-Funktionen, kleines Upload-Limit, Daten-Reset alle 24 h |

Siehe [DEPLOYMENT.md](DEPLOYMENT.md) und die vollständige Funktionsliste in [FEATURES.md](FEATURES.md).

---

## Projektaufbau

```
smdg/
├── app/
│   ├── api/                    # REST: upload, download, auth, admin, webhooks, dicom,
│   │                           # admin_audit_export
│   ├── core/                   # config, DB, security, storage_backend, audit, audit_export
│   ├── crypto/                 # age: Verschlüsselung / Schlüsselrotation
│   ├── models/                 # SQLModel: User, File, FileLink, Tenant, Webhook, DICOM …
│   └── main.py                 # FastAPI, Lifespan, Middleware
├── static/                     # HTML, JS, CSS (Frontend)
├── audit_logs/                 # JSON audit_YYYY-MM-DD.log + CSV (siehe AUDIT_LOGS_DIR)
├── encrypted/
├── decrypted/
├── keys/
├── migrations/
├── tests/
├── docs/                       # Architektur, API, Bereitstellung, DICOM, SECURITY …
├── docker-compose.yml
├── docker-compose.prod.yml
├── Dockerfile
├── entrypoint.sh
├── pyproject.toml
└── README.md
```

| Datei                           | Zweck                                 |
|---------------------------------|---------------------------------------|
| `app/main.py`                   | Lifespan, Middleware, Router          |
| `app/core/config.py`            | Einstellungen (Pydantic Settings)     |
| `app/core/audit_export.py`      | Log-Lesen, Excel/PDF/CSV-Export       |
| `app/api/admin_audit_export.py` | `GET /api/admin/audit/export`         |
| `app/core/storage_backend.py`   | Local / S3                            |
| `scripts/migrate_to_s3.py`      | Migration in den Objektspeicher       |

---

## Sicherheit und Compliance

- Verschlüsselung mit **age**, Passwörter mit **Argon2** gehasht, JWT in **HttpOnly**-Cookies gespeichert
- Richtlinie: [SECURITY.md](SECURITY.md)
- Compliance-Vorlage (FZ-152 / DSGVO): [COMPLIANCE_TEMPLATE.md](COMPLIANCE_TEMPLATE.md)

---

## Dokumentation

| Dokument                                     | Beschreibung                                        |
|----------------------------------------------|-----------------------------------------------------|
| [API_GUIDE.md](API_GUIDE.md)                 | API: Authentifizierung, Limits, DICOM, Audit-Export |
| [ARCHITECTURE.md](ARCHITECTURE.md)           | Architektur, ERD, Diagramme                         |
| [DEPLOYMENT.md](DEPLOYMENT.md)               | Bereitstellung, Abhängigkeiten des Audit-Exports    |
| [DICOM_VIEWER.md](DICOM_VIEWER.md)           | DICOM Viewer                                        |
| [MULTI_TENANCY.md](MULTI_TENANCY.md)         | Mandantenfähigkeit                                  |
| [CHANGELOG.md](CHANGELOG.md)                 | Versionshistorie                                    |
| [SECURITY.md](SECURITY.md)                   | Sicherheitsrichtlinie                               |
| [TESTING.md](TESTING.md)                     | Teststrategie                                       |
| [CONTRIBUTING.md](CONTRIBUTING.md)           | Beitragsleitfaden                                   |
| [COMPLIANCE_TEMPLATE.md](COMPLIANCE_TEMPLATE.md) | FZ-152 / DSGVO Compliance-Vorlage               |

---

## Schnittstellen

| Schnittstelle | URL        |
|---------------|------------|
| Web UI        | `/`        |
| Admin         | `/admin`   |
| Swagger       | `/docs`    |
| Health        | `/health`  |
| Metriken      | `/metrics` |

---

## Lizenz

MIT. Autor: Valeriy Popov.

SMDG — Ihr sicheres Gateway für medizinische Daten.
