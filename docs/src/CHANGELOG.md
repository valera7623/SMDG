# Changelog

> **Translation status:** English stub. The authoritative Russian
> changelog is at [`docs/locales/ru/CHANGELOG.md`](../locales/ru/CHANGELOG.md).
> Entries below are short English summaries.

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/)
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

- New `demo` deployment profile (`DEPLOYMENT_TYPE=demo`): local storage only,
  optional 2FA, small upload cap, public `GET /api/demo/info` endpoint and
  automatic data reset every 24 hours.
- Registration rate limiting (`RATE_LIMIT_REGISTER`, `10/minute` by default,
  `3/hour` in demo) on `POST /api/auth/register`.
- File access audit tree in the admin panel, backed by
  `GET /api/admin/file-audit/`.
- Smooth page transitions across the web UI.

## [4.0.0] — 2026-04

- Full internationalisation (i18n) of the web UI: English / Russian /
  German / French with a runtime language switcher.
- Localised OpenAPI endpoints: `/openapi.ru.json`, `/openapi.de.json`,
  `/openapi.fr.json`.
- Documentation restructured into `docs/src/` (source) and
  `docs/locales/<lang>/` (translations).

## [3.1.0]

- Admin audit export in Excel, PDF and CSV formats with date/user
  filters.

## [3.0.0]

- DICOM Viewer with multi-frame, Window/Level presets and measurements.
- DICOMweb (QIDO-RS, WADO-RS) endpoints.
- OHIF-style viewer integration.

## [2.1.0]

- Webhooks with HMAC-SHA256 signatures and exponential-backoff retry.

## [2.0.0]

- StorageBackend abstraction (Local / S3 with lifecycle rules).
- FS → S3 migration script.

## [1.0.0]

- Initial release: upload/download with age encryption, JWT + 2FA,
  admin panel, audit logs.
