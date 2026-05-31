<!-- smdg-i18n-header-start
source: docs/src/FEATURES.md
source_sha1: 275e7dcf61cbf8cdb3b3ad6ecd16ec00e41b6d78
language: de
last_sync: 2026-05-31
status: translated
smdg-i18n-header-end -->

# SMDG-Funktionsübersicht (Feature Flags)

Funktionen werden über die `FEATURE_MATRIX` in `app/core/feature_flags.py`
abhängig vom Wert von `DEPLOYMENT_TYPE`
(`russia` | `intl` | `single` | `saas` | `demo`) aktiviert.

| Feature                  | Beschreibung                                                            |
|--------------------------|------------------------------------------------------------------------|
| `dicom_viewer`           | DICOM Viewer (in jedem Profil aktiviert)                               |
| `totp_2fa`               | TOTP-Zwei-Faktor-Authentifizierung (in jedem Profil verfügbar)        |
| `s3_storage`             | S3-kompatibler Objektspeicher                                          |
| `local_storage`          | Lokales Dateisystem                                                    |
| `mandatory_2fa`          | Verpflichtende Zwei-Faktor-Authentifizierung                          |
| `gost_crypto`            | GOST-Modus (Stub, erweiterbar durch einen zertifizierten Anbieter)    |
| `audit_3_years`          | Audit-Aufbewahrung von 1095 Tagen (sonst 365)                         |
| `pacs_integration`       | PACS-Integrationen                                                     |
| `gossopka`               | GosSOPKA-Integration (Erweiterungspunkt)                              |
| `multi_tenancy`          | Mandantentrennung pro Tenant (SaaS)                                   |
| `billing`                | Stripe/Paddle-Abrechnung (externe Dienste)                            |
| `white_label`            | White-Label-Branding                                                   |
| `right_to_be_forgotten`  | Verfahren zur Löschung (Recht auf Vergessenwerden, DSGVO)             |
| `data_portability`       | Datenexport für betroffene Personen                                   |
| `auto_ssl`               | Automatisches SSL (Reverse-Proxy / certbot — außerhalb der App)       |
| `auto_backup`            | Backups (Cron / Sidecar)                                              |
| `simple_admin`           | Vereinfachtes Admin-Panel in der UI                                   |

Das `demo`-Profil ist eine Variante für öffentliche Vorführungen: nur lokaler
Speicher, optionale 2FA, aktivierter DICOM-Viewer und DSGVO/HIPAA-orientierte
Funktionen, kleines Upload-Limit und ein automatischer Daten-Reset. Siehe
[`docs/src/DEPLOYMENT.md`](DEPLOYMENT.md) und `.env.demo.example`.

Laufzeitprüfungen:

- HTTP: `GET /health/features`, `GET /health/deployment`
- CLI: `python -m app.cli feature-info` (Zusammenfassung) und
  `python -m app.cli feature-check <feature>` (einzelnes Flag)
