# Secure Medical Data Gateway (SMDG)

**Безопасная передача медицинских файлов с end-to-end шифрованием**

**Текущая версия продукта:** **4.0.0** (ядро и DICOM Viewer); экспорт аудита — **3.1.0**.

SMDG — self-hosted решение для безопасного обмена медицинскими данными между врачами, клиниками и пациентами.
Все файлы шифруются на сервере, имеют временные защищённые ссылки и полный аудит действий.

Подробные руководства лежат в каталоге **[docs/](docs/)** — см. таблицу в разделе «Документация» ниже.

---

## ✨ Основные возможности

### Ядро (v1.0)

- Полное шифрование файлов с помощью **age**
- Антивирусная проверка **ClamAV** перед сохранением
- **JWT** + HttpOnly cookies
- Двухфакторная аутентификация (**TOTP** / 2FA)
- Ролевая модель (**RBAC**): `admin` | `doctor` | `user` | `super_admin` (multi-tenant)
- **Rate limiting** (slowapi + **Redis**)
- Полный **аудит** операций (**JSON** по дням + **CSV** с ротацией)
- **Экспорт аудита** для администратора: **Excel**, **PDF**, **CSV** за период с фильтрами ([API](docs/API_GUIDE.md#11-audit-export-api))
- Удобный веб-интерфейс + админ-панель
- Автоматическая очистка старых файлов и ротация ключей шифрования
- **Docker** + **Docker Secrets**

### Хранилище (v2.0)

- Абстракция **StorageBackend**: **LocalStorageBackend** и **S3StorageBackend**
- S3-совместимые провайдеры: **MinIO**, **Yandex Object Storage**, **Selectel**, **AWS S3**, **DigitalOcean Spaces**
- **S3 Lifecycle Policies** (автоудаление по правилам TTL)
- Скрипт миграции **ФС → S3** (`scripts/migrate_to_s3.py`)

### Webhooks (v2.1)

- События: `file.uploaded`, `file.downloaded`, `file.deleted`
- Подпись payload **HMAC-SHA256**, повторные попытки с **exponential backoff**
- История доставки и статусы в БД

### DICOM Viewer (v3.0)

- Серверный рендеринг **pydicom** + **numpy** + **PIL** → PNG
- Multi-frame (**CT/MRI**) с режимом **Cine**
- Пресеты **Window/Level** (Bone, Lung, Brain, Abdomen, Liver)
- Измерения: линейка, угол, ROI (прямоугольник / эллипс)
- Экспорт PNG / скриншот с аннотациями
- **DICOMweb**: **QIDO-RS** + **WADO-RS**
- Интеграция **OHIF**-style viewer
- **Redis**: кэш метаданных и PNG

Подробнее: [docs/DICOM_VIEWER.md](docs/DICOM_VIEWER.md).

---

## 📋 Минимальные требования

**Для разработки и запуска:**

| Требование              | Минимальная версия           | Рекомендуется          |
|-------------------------|------------------------------|------------------------|
| Docker + Compose        | Docker 24+, Compose v2       | Docker Desktop 4.20+   |
| Python                  | 3.10+                        | 3.12.x                 |
| ОЗУ                     | 4 ГБ                         | 8 ГБ+                  |
| CPU                     | 2 ядра                       | 4+ ядра                |
| Диск                    | 10 ГБ свободно               | 20 ГБ+ (SSD)           |
| ОС                      | Linux / macOS / Windows+WSL2 | Ubuntu 22.04 / 24.04   |

**Для продакшена:** PostgreSQL 15+, Redis 7+, ClamAV, 8+ ГБ ОЗУ.

---

## 🚀 Быстрый старт

### Локальный запуск (Development)

```bash
git clone <ваш-репозиторий>
cd smdg

cp .env.example .env
docker compose up --build
```

Приложение: **https://localhost** (или HTTP-порт из compose).

### Production

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

### Запуск с MinIO (S3)

```bash
# В .env:
S3_ENABLED=true
S3_ACCESS_KEY=minioadmin
S3_SECRET_KEY=minioadmin123

docker compose --profile s3 up -d
```

Консоль MinIO: http://localhost:9001

### Миграция данных ФС → S3

```bash
python scripts/migrate_to_s3.py --dry-run
python scripts/migrate_to_s3.py --delete-local
```

---

## Типы развёртывания (Feature Flags)

Один код собирается под несколько профилей через **`DEPLOYMENT_TYPE`** (`russia` | `intl` | `single` | `saas`): матрица фич в `app/core/feature_flags.py`, проверки в `GET /health/features` и CLI `python -m app.cli feature-info`.

| Профиль  | Кратко                                                                                        |
|----------|-----------------------------------------------------------------------------------------------|
| `russia` | ФЗ-152: локальное хранилище, DICOM, обязательная 2FA в политике, аудит 3 года, задел под ГОСТ |
| `intl`   | S3/MinIO, DICOM, GDPR/HIPAA-ориентированные фичи, 2FA                                         |
| `single` | Один tenant, упрощённая админка,DICOM, 2FA, локальный диск по умолчанию                       |
| `saas`   | Multi-tenant, биллинг/white-label в матрице, объектное хранилище, DICOM, 2FA                  |

Подробнее: [DEPLOYMENT.md](DEPLOYMENT.md), список фич: [FEATURES.md](FEATURES.md).

---

## 📁 Структура проекта

```
smdg/
├── app/
│   ├── api/                    # REST: upload, download, auth, admin, webhooks, dicom,
│   │                           # admin_audit_export (экспорт аудита)
│   ├── core/                   # config, БД, security, storage_backend, audit, audit_export
│   ├── crypto/                 # age: шифрование / ротация ключей
│   ├── models/                 # SQLModel: User, File, FileLink, Tenant, Webhook, DICOM …
│   ├── static/                 # HTML, JS, CSS
│   └── main.py                 # FastAPI, lifespan, middleware
├── audit_logs/                 # JSON audit_YYYY-MM-DD.log + CSV (настраивается AUDIT_LOGS_DIR)
├── encrypted/
├── decrypted/
├── keys/
├── migrations/
├── tests/
├── docs/                       # Архитектура, API, деплой, DICOM, SECURITY …
├── docker-compose.yml
├── docker-compose.prod.yml
├── Dockerfile
├── entrypoint.sh
├── pyproject.toml
└── README.md
```

| Файл                            | Назначение                          |
|---------------------------------|-------------------------------------|
| `app/main.py`                   | Lifespan, middleware, роутеры       |
| `app/core/config.py`            | Настройки (Pydantic Settings)       |
| `app/core/audit_export.py`      | Чтение логов, Excel/PDF/CSV экспорт |
| `app/api/admin_audit_export.py` | `GET /api/admin/audit/export`       |
| `app/core/storage_backend.py`   | Local / S3                          |
| `scripts/migrate_to_s3.py`      | Миграция в объектное хранилище      |

---

## 🔐 Безопасность и соответствие

- Шифрование **age**, пароли **Argon2**, JWT в **HttpOnly** cookie  
- Политика: [docs/SECURITY.md](docs/SECURITY.md)  
- Шаблон соответствия ФЗ-152 / GDPR: [docs/COMPLIANCE_TEMPLATE.md](docs/COMPLIANCE_TEMPLATE.md)  

---

## 📄 Документация

| Документ                                                   | Описание                                               |
|------------------------------------------------------------|--------------------------------------------------------|
| [docs/API_GUIDE.md](docs/API_GUIDE.md)                     | API: аутентификация, лимиты, DICOM, **экспорт аудита** |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)               | Архитектура, ERD, диаграммы                            |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)                   | Развёртывание, зависимости экспорта аудита             |
| [docs/DICOM_VIEWER.md](docs/DICOM_VIEWER.md)               | DICOM Viewer                                           |
| [docs/MULTI_TENANCY.md](docs/MULTI_TENANCY.md)             | Multi-tenancy                                          |
| [docs/CHANGELOG.md](docs/CHANGELOG.md)                     | История версий                                         |
| [docs/SECURITY.md](docs/SECURITY.md)                       | Безопасность                                           |
| [docs/TESTING.md](docs/TESTING.md)                         | Стратегия тестирования                                 |
| [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md)               | Участие в проекте                                      |
| [docs/COMPLIANCE_TEMPLATE.md](docs/COMPLIANCE_TEMPLATE.md) | Шаблон соответствия ФЗ-152 / GDPR                      |

---

## 📊 Интерфейсы

| Интерфейс    | URL        |
|--------------|------------|
| Веб-UI       | `/`        |
| Админ-панель | `/admin`   |
| Swagger      | `/docs`    |
| Health       | `/health`  |
| Метрики      | `/metrics` |

---

## 📄 Лицензия

MIT. Автор: Валерий Попов.

SMDG — ваш безопасный шлюз для медицинских данных.
