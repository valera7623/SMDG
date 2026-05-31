<!-- smdg-i18n-header-start
source: docs/src/FEATURES.md
source_sha1: 275e7dcf61cbf8cdb3b3ad6ecd16ec00e41b6d78
language: ru
last_sync: 2026-05-31
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
