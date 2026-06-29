# Changelog

История версий SMDG. Формат: [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

- Профиль `demo`: локальное хранилище, опциональная 2FA, сброс данных раз в 24 ч.
- Rate limiting регистрации (`RATE_LIMIT_REGISTER`).
- Аудит доступа к файлам в админ-панели (`GET /api/admin/file-audit/`).
- Плавные переходы между страницами UI.
- MkDocs-документация (как MedInsight).

## [4.0.0] — 2026-04

- Полная i18n веб-интерфейса: EN / RU / DE / FR.
- Локализованные OpenAPI: `/openapi.ru.json`, `/openapi.de.json`, `/openapi.fr.json`.
- Реструктуризация docs: `docs/src/` + `docs/locales/`.

## [3.1.0]

- Экспорт аудита: Excel, PDF, CSV с фильтрами.

## [3.0.0]

- DICOM Viewer: multi-frame, Window/Level, измерения.
- DICOMweb (QIDO-RS, WADO-RS).
- OHIF-style viewer.

## [2.1.0]

- Webhooks: HMAC-SHA256, exponential backoff.

## [2.0.0]

- StorageBackend (Local / S3), lifecycle policies.
- Миграция ФС → S3.

## [1.0.0]

- Первый релиз: age, JWT + 2FA, админка, аудит.

Полная версия: [src/CHANGELOG.md](../src/CHANGELOG.md).
