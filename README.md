# Secure Medical Data Gateway (SMDG)

**Безопасная передача медицинских файлов с end-to-end шифрованием**

SMDG — self-hosted решение для безопасного обмена медицинскими данными между врачами, клиниками и пациентами.
Все файлы шифруются на сервере, имеют временные защищённые ссылки и полный аудит действий.

---

## ✨ Основные возможности

- Полное шифрование файлов с помощью **age**
- Временные одноразовые ссылки (TTL + ограничение скачиваний)
- Антивирусная проверка **ClamAV** перед сохранением
- Двухфакторная аутентификация (TOTP + QR-код)
- Ролевая модель: `admin` | `doctor` | `user`
- Полный аудит всех операций (JSON + CSV)
- Автоматическая очистка старых файлов
- Ротация ключей шифрования с перешифровкой
- Удобный веб-интерфейс + админ-панель
- Rate limiting и защита от brute-force
- Полная поддержка Docker + Docker Secrets
- **Гибридное хранилище:** локальная ФС или **S3/MinIO** (Yandex Object Storage, Selectel, AWS S3)
- **Webhook-уведомления** о событиях (upload, download, delete) с HMAC подписью и retry
- **DICOM Viewer** — просмотр медицинских изображений прямо в браузере (pydicom + numpy + PIL)
- **DICOMweb API** — QIDO-RS + WADO-RS совместимые эндпоинты

---

## 📋 Минимальные требования

**Для разработки и запуска:**

| Требование              | Минимальная версия          | Рекомендуется          |
|-------------------------|-----------------------------|------------------------|
| Docker + Compose        | Docker 24+, Compose v2      | Docker Desktop 4.20+   |
| Python                  | 3.12                        | 3.12.3                 |
| ОЗУ                     | 4 ГБ                        | 8 ГБ+                  |
| CPU                     | 2 ядра                      | 4+ ядра                |
| Диск                    | 10 ГБ свободно              | 20 ГБ+ (SSD)           |
| ОС                      | Linux / macOS / Windows+WSL2| Ubuntu 22.04 / 24.04   |

**Для продакшена:**
- PostgreSQL 15+
- Redis 7+
- ClamAV (daemon)
- 8+ ГБ ОЗУ и 4+ ядра

---

## 🚀 Быстрый старт

### 1. Локальный запуск (Development)

```bash
# 1. Клонируйте репозиторий
git clone <ваш-репозиторий>
cd smdg

# 2. Скопируйте переменные окружения
cp .env.example .env

# 3. Запустите все сервисы
docker compose up --build

Приложение будет доступно по адресу: https://localhost

### 2. Production запуск

docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d

### 3. Запуск с MinIO (S3-режим)

Для разработки с S3-совместимым хранилищем:

```bash
# В .env установите:
S3_ENABLED=true
S3_ACCESS_KEY=minioadmin
S3_SECRET_KEY=minioadmin123

# Запуск с MinIO
docker compose --profile s3 up -d
```

MinIO Console будет доступна по адресу: http://localhost:9001

### 4. Миграция данных из ФС в S3

Если вы переходите с локального хранилища на S3:

```bash
# Проверка (dry-run)
python scripts/migrate_to_s3.py --dry-run

# Реальная миграция с удалением локальных файлов
python scripts/migrate_to_s3.py --delete-local
```

---

## 📁 Структура проекта

smdg/
├── app/                          # Основной код приложения
│   ├── api/                      # Все REST-эндпоинты (upload, download, auth, admin_users и т.д.)
│   ├── core/                     # Ядро: конфигурация, БД, security, cleanup, audit, rate limiting
│   ├── crypto/                   # Логика шифрования age (encrypt/decrypt + ротация ключей)
│   ├── models/                   # SQLModel-модели БД (User, File, FileLink)
│   ├── static/                   # Фронтенд (HTML, JS, CSS, QR-код)
│   └── main.py                   # Входная точка: FastAPI app, lifespan events, middleware
├── encrypted/                    # Зашифрованные медицинские файлы (постоянное хранение)
├── decrypted/                    # Временные расшифрованные файлы (автоудаляются по TTL)
├── keys/                         # Ключи age (age.key + age.pub) — монтируются через Docker Secrets
├── audit_logs/                   # Логи аудита (JSON по дням + CSV)
├── migrations/                   # Alembic-миграции БД
├── tests/                        # Все тесты (unit, integration, e2e)
├── .github/workflows/            # GitHub Actions CI/CD
├── docker-compose.yml            # Основной compose для разработки
├── docker-compose.prod.yml       # Production-конфигурация (лимиты ресурсов, secrets)
├── Dockerfile                    # Сборка образа приложения
├── entrypoint.sh                 # Запуск внутри контейнера (миграции, создание админа)
├── pyproject.toml                # Зависимости и настройки Poetry
└── README.md                     # Этот файл

Ключевые файлы, которые стоит знать:

Файл	                    Назначение
app/main.py	                Lifespan events, middleware, подключение роутеров
app/core/config.py	        Все настройки (Pydantic Settings)
app/core/security.py	    JWT, Argon2, 2FA
app/crypto/crypto.py	    Шифрование/расшифровка age
app/core/storage.py	        Управление временными файлами и TTL
app/core/storage_backend.py	Абстракция хранилища (Local + S3/MinIO)
app/core/audit.py	        Централизованный аудит
app/core/cleanup.py	        Автоматическая очистка
scripts/migrate_to_s3.py	Скрипт миграции ФС → S3

---

## 💾 Режимы хранения файлов

SMDG поддерживает два режима хранения зашифрованных файлов:

| Режим                           | Описание                                   |         Когда использовать                      |
|---------------------------------|--------------------------------------------|-------------------------------------------------|
| **Локальная ФС** (по умолчанию) | Файлы хранятся в `/app/encrypted` на хосте | Dev, небольшие проекты, isolated серверы        |
| **S3/MinIO**                    | Файлы хранятся в S3-совместимом хранилище  | Production, масштабирование, внешние облака     |

### Поддерживаемые S3-провайдеры

| Провайдер                  | Endpoint                                  | SSL| Примечание                     |
|----------------------------|-------------------------------------------|----|--------------------------------|
| **MinIO** (self-hosted)    | `http://minio:9000`                       | Нет| Dev/test, полный контроль      |
| **Yandex Object Storage**  | `https://storage.yandexcloud.net`         | Да | Российские дата-центры, ФЗ-152 |
| **Selectel Cloud Storage** | `https://s3.selcdn.ru`                    | Да | Российский облако              |
| **AWS S3**                 | `https://s3.amazonaws.com`                | Да | Глобальный, не для ФЗ-152      |
| **DigitalOcean Spaces**    | `https://<region>.digitaloceanspaces.com` | Да | Простая настройка              |

### Конфигурация S3

```bash
# В .env или .env.prod:
S3_ENABLED=true
S3_ENDPOINT_URL=http://minio:9000          # или внешний S3 endpoint
S3_ACCESS_KEY=your_access_key
S3_SECRET_KEY=your_secret_key
S3_BUCKET_ENCRYPTED=smdg-encrypted         # бакет для зашифрованных файлов
S3_BUCKET_UPLOADS=smdg-uploads             # временный бакет для загрузок
S3_BUCKET_DECRYPTED=smdg-decrypted         # временный бакет для расшифровок
S3_REGION=us-east-1
S3_USE_SSL=false                           # true для внешних S3 провайдеров
```

---

## 🔐 Безопасность

Все файлы шифруются до записи на диск
Пароли — только Argon2
2FA (TOTP) является обязательной рекомендацией (см. SECURITY.md)
Rate limiting + полный аудит
Docker Secrets для ключей и паролей

Подробно: SECURITY.md

📋 Соответствие регуляторным требованиям
⚠️ Важно: Документ COMPLIANCE_TEMPLATE.md является шаблоном для адаптации под вашу организацию. Перед использованием в production заполните все поля в квадратных скобках и проконсультируйтесь с юристом.

→ COMPLIANCE_TEMPLATE.md — ФЗ-152, GDPR (шаблон)

📊 Доступные интерфейсы
Интерфейс                    URL	                           Описание
Главная страница	         /	                               Веб-интерфейс пользователя
Админ-панель	             /admin	                           Управление пользователями
Swagger UI	                 /docs	                           Интерактивная API документация
ReDoc	                     /redoc	                           Альтернативная API документация
OpenAPI JSON	             /openapi.json	                   Машинно-читаемая спецификация
Healthcheck	                 /health	                       Статус сервиса
Prometheus metrics	         /metrics	                       Метрики для мониторинга

📄 Документация
Документ	                            Описание
API.md	                                Концептуальный гайд по API + ссылки на OpenAPI
ARCHITECTURE.md	                        Архитектура системы, диаграммы, ERD
DEPLOYMENT.md	                        Развёртывание в production
DICOM_VIEWER.md                         DICOM-вьюер
SECURITY.md	                            Политика безопасности, threat model
COMPLIANCE_TEMPLATE.md	                Шаблон соответствия ФЗ-152/GDPR
TESTING.md	                            Стратегия тестирования, coverage (93%)
TROUBLESHOOTING.md	                    Решение типовых проблем
CHANGELOG.md	                        История версий
CONTRIBUTING.md                         Сотрудничество

🤝 Внесение изменений
Проект находится в приватной разработке. Подробности см. в CONTRIBUTING.md.

📄 Лицензия
Проект распространяется под лицензией MIT.
Автор: Валерий Попов

SMDG — ваш безопасный шлюз для медицинских данных.






