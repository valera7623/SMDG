<!-- smdg-i18n-header-start
source: docs/src/CHANGELOG.md
source_sha1: e06f9cfeba9a9218a2cbcda27089ce85f7890a66
language: ru
last_sync: 2026-04-20
status: needs-translation
smdg-i18n-header-end -->

# Changelog

Все значимые изменения в проекте **Secure Medical Data Gateway (SMDG)** будут документироваться в этом файле.

Формат основан на [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
версионирование соответствует [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

## [3.1.0] - 2026-04-18

### Added
- **Экспорт журнала аудита для администратора** — `GET /api/admin/audit/export`
- Форматы отчёта: **Excel** (`.xlsx`, листы «Сводка» и «Детали»), **PDF** (DejaVuSans, кириллица), **CSV** (`;`, UTF-8 BOM для Excel)
- Параметры: `format`, `start_date`, `end_date`, опционально `user_id` (поле `user` в JSON), `event_type` (поле `action`)
- Асинхронное построчное чтение логов через **aiofiles** из каталога **`AUDIT_LOGS_DIR`** (`audit_logs_dir` в настройках)
- Настройки: `AUDIT_EXPORT_PDF_FONT_PATH`, `AUDIT_EXPORT_DOWNLOAD_PREFIX`
- Зависимости: **openpyxl**, **reportlab** ( **aiofiles** уже используется в проекте)
- Модули: `app/core/audit_export.py`, `app/api/admin_audit_export.py`; запись аудита перенаправлена на `settings.audit_logs_dir` для согласованности с экспортом

### Security
- Экспорт аудита доступен только ролям **admin** / **super_admin** (`get_current_admin`)

## [3.0.0] - 2026-04-12

### Added
- **DICOM Viewer** — встроенный просмотр медицинских изображений
- **pydicom + numpy + PIL** — серверный рендеринг DICOM в PNG
- **Redis-кэш метаданных** — 30+ DICOM-тегов с TTL 2.25 часа
- **Реальные DICOM UIDs** — StudyInstanceUID, SeriesInstanceUID, SOPInstanceUID из файла
- **QIDO-RS эндпоинты** — `/api/dicom/qido/studies`, `/series`, `/instances`
- **WADO-RS эндпоинт** — `/api/dicom/wado/studies/{s}/series/{se}/instances/{i}`
- **DICOMweb совместимость** — формат ответов `application/dicom+json`
- **Модель DicomViewToken** — временные токены для просмотра (TTL 15 мин)
- **Alembic миграция** — таблица `dicom_view_tokens`
- **Feature Flag** — `DICOM_VIEWER_ENABLED` в config
- **Аудит DICOM** — `dicom.view_initiated`, `dicom.streamed`, `dicom.metadata_accessed`
- **Инструменты viewer** — Zoom, Pan, Window/Level, Invert, Metadata sidebar
- **Зависимости:** pydicom, numpy, pillow
- **Nginx CSP** — расширенные заголовки для DICOM Viewer

## [2.1.0] - 2026-04-10

### Added
- **Webhook-уведомления** о событиях: file.uploaded, file.downloaded, file.deleted
- **CRUD API** для управления webhook-подписками (`/api/webhooks`)
- **История доставки** webhook-уведомлений с статусом и количеством попыток
- **HMAC-SHA256 подпись** payload для безопасности webhook
- **Retry mechanism** с exponential backoff (до 10 попыток, до 5 минут задержка)
- **Фоновый retry scheduler** — проверка каждые 30 секунд
- **Webhook ping endpoint** — тестирование подписки
- **Модели БД:** WebhookSubscription, WebhookDelivery
- **Alembic миграция 002** — таблицы webhook_subscriptions и webhook_deliveries
- **19 тестов** для webhook системы

## [2.0.0] - 2026-04-10

### Added
- **Гибридное хранилище:** поддержка S3/MinIO для хранения зашифрованных файлов
- **StorageBackend абстракция:** `LocalStorageBackend` + `S3StorageBackend` через `StorageFactory`
- **MinIO сервис** в docker-compose (запускается через `--profile s3`)
- **Скрипт миграции:** `scripts/migrate_to_s3.py` для переноса данных из ФС в S3
- **Скрипт инициализации:** `scripts/init_s3_buckets.sh` для создания S3 бакетов
- **Поддержка S3-провайдеров:** MinIO, Yandex Object Storage, Selectel, AWS S3, DigitalOcean Spaces
- **S3 настройки в .env:** `S3_ENABLED`, `S3_ENDPOINT_URL`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_BUCKET_*`
- **Интеграция API:** upload, download, delete, list, stats, cleanup теперь работают с обоими режимами
- **FileCleanupManager** обновлён для работы с StorageBackend
- **entrypoint.sh** автоматически инициализирует S3 бакеты при старте
- **aiobotocore** зависимость для асинхронной работы с S3
- **39 новых тестов:** 22 для LocalStorageBackend + 17 для S3StorageBackend

### Changed
- `encrypted_path` в БД теперь хранит S3 object key вместо локального пути
- `_get_storage_stats()` и `_get_files_stats()` стали async функциями
- `FileCleanupManager` принимает опциональный `storage_backend` параметр

### Deprecated
- Прямое использование `ENCRYPTED_DIR` в API — используйте `encrypted_storage` вместо этого

### Security
- S3 bucket policy автоматически устанавливается в dev mode
- Все S3 операции используют HTTPS в production (`S3_USE_SSL=true`)

## [1.0.0] - 2026-04-05

### Added
- **Полноценная система шифрования** файлов с помощью **age** (asymmetric encryption)
- **Загрузка и скачивание файлов** с автоматическим шифрованием/расшифровкой
- **Временные одноразовые ссылки** с поддержкой TTL и ограничения по количеству скачиваний
- **Двухфакторная аутентификация (2FA/TOTP)** с генерацией QR-кода
- **Ролевая модель доступа**: `admin`, `doctor`, `user`
- **Полноценная админ-панель** для управления пользователями (создание, редактирование, массовые операции)
- **Система аудита** всех действий (JSON + CSV логи с ротацией)
- **Автоматическая очистка** старых файлов через APScheduler
- **Ротация ключей шифрования** с перешифровкой всех существующих файлов (CLI-команда)
- **Rate limiting** на все критичные эндпоинты (slowapi + Redis)
- **Docker + docker-compose** конфигурация (dev + production)
- **CI/CD** через GitHub Actions (тесты, coverage, Bandit, сборка Docker-образа)
- **Prometheus + Grafana** мониторинг
- **Health-check** и метрики системы
- **CLI-утилиты** (`create-admin`, `rotate-keys`)

### Security
- Пароли хранятся только в **Argon2**
- JWT-токены в **HttpOnly cookies**
- Все секреты вынесены в **Docker Secrets**
- Защита от загрузки опасных файлов (валидация MIME + расширений)
- Полный аудит действий с фиксацией пользователя, IP и результата

### Infrastructure
- Полная контейнеризация всех сервисов (FastAPI, PostgreSQL, Redis, Nginx)
- Разделение конфигурации на `docker-compose.yml` и `docker-compose.prod.yml`
- Автоматические миграции БД через Alembic
- Генерация self-signed сертификатов для локальной разработки

### Fixed
- Исправлены проблемы с порядком аргументов в `crypto_manager.decrypt_file()`
- Улучшена обработка ошибок и логирование в модулях загрузки/скачивания
- Исправлены middleware и контекст пользователя

### Changed
- Переход на Poetry как менеджер зависимостей
- Улучшена структура проекта (разделение core, api, models)
- Обновлена фронтенд-часть (современный UI + улучшенная UX)

---

## [0.1.0] - 2026-03 (Предварительная версия)

- Начальная архитектура проекта
- Базовая загрузка и скачивание файлов
- Подключение PostgreSQL и Redis
- Начальная настройка Docker

---

**Примечание:**  
Начиная с версии 1.0.0 проект считается стабильным и готовым к использованию в production-среде.

---
