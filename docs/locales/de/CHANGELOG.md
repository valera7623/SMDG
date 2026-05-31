<!-- smdg-i18n-header-start
source: docs/src/CHANGELOG.md
source_sha1: 6f148bebc20423b8db6fe49ef992df783e73d09e
language: de
last_sync: 2026-05-31
status: translated
smdg-i18n-header-end -->

# Änderungsprotokoll

> **Übersetzungsstatus:** deutsche Übersetzung. Die maßgebliche russische
> Version des Änderungsprotokolls befindet sich unter
> [`docs/locales/ru/CHANGELOG.md`](../ru/CHANGELOG.md).

Alle nennenswerten Änderungen an diesem Projekt werden in dieser Datei
dokumentiert. Das Format basiert auf [Keep a Changelog](https://keepachangelog.com/)
und das Projekt folgt der [semantischen Versionierung](https://semver.org/).

## [Unveröffentlicht]

- Neues Bereitstellungsprofil `demo` (`DEPLOYMENT_TYPE=demo`): nur lokaler
  Speicher, optionale 2FA, kleines Upload-Limit, öffentlicher Endpunkt
  `GET /api/demo/info` und automatischer Daten-Reset alle 24 Stunden.
- Ratenbegrenzung bei der Registrierung (`RATE_LIMIT_REGISTER`, standardmäßig
  `10/minute`, `3/hour` im Demo-Modus) für `POST /api/auth/register`.
- Audit-Baum für Dateizugriffe im Admin-Panel, bereitgestellt über
  `GET /api/admin/file-audit/`.
- Sanfte Seitenübergänge in der gesamten Web-Oberfläche.

## [4.0.0] — 2026-04

- Vollständige Internationalisierung (i18n) der Web-Oberfläche: Englisch /
  Russisch / Deutsch / Französisch mit einem Sprachumschalter zur Laufzeit.
- Lokalisierte OpenAPI-Endpunkte: `/openapi.ru.json`, `/openapi.de.json`,
  `/openapi.fr.json`.
- Dokumentation neu strukturiert in `docs/src/` (Quelle) und
  `docs/locales/<lang>/` (Übersetzungen).

## [3.1.0]

- Admin-Audit-Export in den Formaten Excel, PDF und CSV mit Datums- und
  Benutzerfiltern.

## [3.0.0]

- DICOM Viewer mit Multi-Frame, Window/Level-Voreinstellungen und Messungen.
- DICOMweb-Endpunkte (QIDO-RS, WADO-RS).
- Integration im OHIF-Stil.

## [2.1.0]

- Webhooks mit HMAC-SHA256-Signaturen und Wiederholungen mit exponentiellem
  Backoff.

## [2.0.0]

- StorageBackend-Abstraktion (Local / S3 mit Lifecycle-Regeln).
- Migrationsskript FS → S3.

## [1.0.0]

- Erste Veröffentlichung: Upload/Download mit age-Verschlüsselung, JWT + 2FA,
  Admin-Panel, Audit-Protokolle.
