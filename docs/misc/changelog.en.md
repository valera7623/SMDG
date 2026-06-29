# Changelog

SMDG version history. Format: [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

- `demo` profile: local storage, optional 2FA, 24 h data reset.
- Registration rate limiting (`RATE_LIMIT_REGISTER`).
- File access audit in admin panel (`GET /api/admin/file-audit/`).
- Smooth UI page transitions.
- MkDocs documentation (MedInsight-style).

## [4.0.0] — 2026-04

- Full web UI i18n: EN / RU / DE / FR.
- Localised OpenAPI: `/openapi.ru.json`, `/openapi.de.json`, `/openapi.fr.json`.
- Docs restructure: `docs/src/` + `docs/locales/`.

## [3.1.0]

- Audit export: Excel, PDF, CSV with filters.

## [3.0.0]

- DICOM Viewer: multi-frame, Window/Level, measurements.
- DICOMweb (QIDO-RS, WADO-RS).
- OHIF-style viewer.

## [2.1.0]

- Webhooks: HMAC-SHA256, exponential backoff.

## [2.0.0]

- StorageBackend (Local / S3), lifecycle policies.
- FS → S3 migration.

## [1.0.0]

- Initial release: age, JWT + 2FA, admin panel, audit.

Full version: [src/CHANGELOG.md](../src/CHANGELOG.md).
