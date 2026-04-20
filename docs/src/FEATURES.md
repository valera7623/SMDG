# SMDG feature map (Feature Flags)

Features are enabled by the `FEATURE_MATRIX` in `app/core/feature_flags.py`
depending on the value of `DEPLOYMENT_TYPE`.

| Feature                  | Description                                                             |
|--------------------------|-------------------------------------------------------------------------|
| `s3_storage`             | S3-compatible object storage                                            |
| `local_storage`          | Local filesystem                                                        |
| `mandatory_2fa`          | Mandatory two-factor authentication                                     |
| `gost_crypto`            | GOST mode (stub that is extended by a certified provider)               |
| `audit_3_years`          | Audit retention of 1095 days (otherwise 365)                            |
| `dicom_viewer`           | DICOM Viewer                                                            |
| `pacs_integration`       | PACS integrations                                                       |
| `gossopka`               | GosSOPKA integration (extension point)                                  |
| `multi_tenancy`          | Per-tenant isolation (SaaS)                                             |
| `billing`                | Stripe/Paddle billing (external services)                               |
| `white_label`            | White-label branding                                                    |
| `right_to_be_forgotten`  | Right-to-erasure procedures (GDPR)                                      |
| `data_portability`       | Data subject export                                                     |
| `auto_ssl`               | Automatic SSL (handled by reverse proxy / certbot — outside the app)    |
| `auto_backup`            | Backups (cron / sidecar)                                                |
| `simple_admin`           | Simplified admin panel in the UI                                        |

Runtime checks:

- HTTP: `GET /health/features`, `GET /health/deployment`
- CLI: `python -m app.cli feature-info`
