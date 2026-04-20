<!-- smdg-i18n-header-start
source: docs/src/FEATURES.md
source_sha1: 614bb36e24be290b9a6d2e0d7c691b9af5ec8306
language: ru
last_sync: 2026-04-20
status: needs-translation
smdg-i18n-header-end -->

# Карта фич SMDG (Feature Flags)

Фичи включаются матрицей `FEATURE_MATRIX` в `app/core/feature_flags.py` в зависимости от `DEPLOYMENT_TYPE`.

| Feature                  | Описание                                                           |
|--------------------------|--------------------------------------------------------------------|
| `s3_storage`             | Объектное хранилище S3-совместимое                                 |
| `local_storage`          | Локальная файловая система                                         |
| `mandatory_2fa`          | Обязательная двухфакторная аутентификация                          |
| `gost_crypto`            | Режим ГОСТ (заглушка расширяется до сертифицированного провайдера) |
| `audit_3_years`          | Хранение аудита 1095 дней (иначе 365)                              |
| `dicom_viewer`           | DICOM Viewer                                                       |
| `pacs_integration`       | Интеграции PACS                                                    |
| `gossopka`               | Интеграция с ГосСОПКА (точка расширения)                           |
| `multi_tenancy`          | Изоляция по tenant (SaaS)                                          |
| `billing`                | Биллинг Stripe/Paddle (внешние сервисы)                            |
| `white_label`            | White-label брендинг                                               |
| `right_to_be_forgotten`  | Процедуры удаления данных (GDPR)                                   |
| `data_portability`       | Экспорт данных субъекта                                            |
| `auto_ssl`               | Авто SSL (reverse-proxy / certbot — вне приложения)                |
| `auto_backup`            | Резервное копирование (cron / sidecar)                             |
| `simple_admin`           | Упрощённая админ-панель в UI                                       |

Проверка в рантайме:

- HTTP: `GET /health/features`, `GET /health/deployment`
- CLI: `python -m app.cli feature-info`
