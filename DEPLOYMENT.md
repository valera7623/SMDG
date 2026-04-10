# DEPLOYMENT.md

**Secure Medical Data Gateway (SMDG)** — Руководство по развертыванию

**Версия:** 2.0
**Дата:** 10 апреля 2026

---

## 1. Обзор

SMDG полностью контейнеризирован и разворачивается через **Docker Compose**.
Поддерживаются два режима:

- **Development** — для локальной разработки и тестирования
- **Production** — для боевого окружения (рекомендуемый)

Используется многоуровневая конфигурация:
- `docker-compose.yml` (базовый)
- `docker-compose.prod.yml` (переопределения для продакшена)

**Новое в v2.0:** Поддержка S3/MinIO для масштабируемого хранения файлов.

---

## 2. Требования к серверу (Production)

| Компонент          | Минимальные требования          | Рекомендуемые              |
|--------------------|---------------------------------|----------------------------|
| CPU                | 2 ядра                          | 4+ ядра                    |
| RAM                | 4 GB                            | 8+ GB                      |
| Диск               | 50 GB SSD                       | 100+ GB NVMe               |
| ОС                 | Linux (Ubuntu 22.04/24.04)      | Ubuntu 24.04 LTS           |
| Docker + Compose   | Docker 24+, Compose v2          | Последние версии           |

---

## 3. Подготовка сервера

```bash
# Обновление системы
sudo apt update && sudo apt upgrade -y

# Установка Docker и Docker Compose
sudo apt install docker.io docker-compose-plugin -y
sudo usermod -aG docker $USER
newgrp docker
```

## 4. Подготовка секретов (обязательно!)

Создайте папку `secrets/` и положите туда файлы:

```bash
mkdir -p secrets

# Генерация необходимых секретов
echo "your-super-strong-jwt-secret-key-min-48-chars" > secrets/jwt_secret.txt
echo "ChangeMe123!StrongPasswordForAdmin" > secrets/admin_password.txt
echo "your-postgres-password-here" > secrets/postgres_password.txt
echo "StrongGrafanaPass123!" > secrets/grafana_password.txt

# Ключ age (если нет — будет создан автоматически при первом запуске)
# Рекомендуется сгенерировать заранее:
age-keygen -o secrets/age.key
chmod 600 secrets/age.key
```

**Важно:** Никогда не коммитьте папку `secrets/` в Git!

## 5. Настройка окружения

### Development (`.env`)

```bash
cp .env.example .env

# Отредактируйте .env под себя
```

### Production (`.env.prod`)

Создайте файл `.env.prod`:

```bash
DOCKER_USERNAME=<your-docker-username>
IMAGE_TAG=latest
DOMAIN=<your-domain>
REDIS_PASSWORD=<your-redis-password>
```

---

## 6. Выбор режима хранилища

SMDG поддерживает два режима хранения зашифрованных файлов:

### 6.1 Локальная файловая система (по умолчанию)

```bash
# В .env или .env.prod:
S3_ENABLED=false
```

Файлы хранятся в директории `/app/encrypted` на хосте. Подходит для:
- Разработки и тестирования
- Небольших проектов
- Изолированных серверов с достаточным дисковым пространством

### 6.2 S3/MinIO (рекомендуется для production)

#### Вариант A: MinIO (self-hosted, dev/test)

```bash
# В .env:
S3_ENABLED=true
S3_ENDPOINT_URL=http://minio:9000
S3_ACCESS_KEY=minioadmin
S3_SECRET_KEY=minioadmin123
S3_USE_SSL=false

# Запуск с MinIO
docker compose --profile s3 up -d
```

MinIO Console: http://localhost:9001

#### Вариант B: Yandex Object Storage (production, ФЗ-152)

```bash
# В .env.prod:
S3_ENABLED=true
S3_ENDPOINT_URL=https://storage.yandexcloud.net
S3_ACCESS_KEY=<your_yandex_access_key>
S3_SECRET_KEY=<your_yandex_secret_key>
S3_USE_SSL=true
S3_REGION=ru-central1
```

#### Вариант C: Selectel Cloud Storage

```bash
# В .env.prod:
S3_ENABLED=true
S3_ENDPOINT_URL=https://s3.selcdn.ru
S3_ACCESS_KEY=<your_selectel_access_key>
S3_SECRET_KEY=<your_selectel_secret_key>
S3_USE_SSL=true
S3_REGION=ru-1
```

#### Вариант D: AWS S3

```bash
# В .env.prod:
S3_ENABLED=true
S3_ENDPOINT_URL=https://s3.amazonaws.com
S3_ACCESS_KEY=<your_aws_access_key>
S3_SECRET_KEY=<your_aws_secret_key>
S3_USE_SSL=true
S3_REGION=eu-west-1
```

---

## 7. Запуск

### 7.1 Development режим (локальное хранилище)

```bash
docker compose up --build -d
```

Приложение будет доступно по http://localhost

### 7.2 Development режим с MinIO

```bash
docker compose --profile s3 up -d
```

### 7.3 Production режим (рекомендуется)

Первый запуск (сборка образа):

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

Последующие запуски:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

Приложение будет доступно по HTTPS через Nginx.

---

## 8. Миграция данных из ФС в S3

Если вы уже используете SMDG с локальным хранилищем и хотите перейти на S3:

### 8.1 Подготовка

1. Убедитесь что S3 endpoint доступен
2. Настройте переменные S3 в `.env` / `.env.prod`
3. Остановите приложение: `docker compose down`

### 8.2 Проверка (dry-run)

```bash
# Запустите скрипт миграции в режиме проверки
docker compose run --rm smdg python scripts/migrate_to_s3.py --dry-run
```

### 8.3 Реальная миграция

```bash
# Миграция с удалением локальных файлов после успешной загрузки
docker compose run --rm smdg python scripts/migrate_to_s3.py --delete-local
```

### 8.4 Переключение на S3 режим

После миграции обновите `.env` / `.env.prod`:

```bash
S3_ENABLED=true
```

И перезапустите:

```bash
docker compose up -d
```

---

## 9. После первого запуска

Проверьте логи:

```bash
docker compose logs -f smdg
```

Создайте первого администратора (если не создан автоматически):

```bash
docker compose exec smdg python -m app.cli create-admin \
  <admin-username> <strong-password> <admin@your-domain.com>
```

Проверьте работоспособность:
- http://ваш-домен/health
- http://ваш-домен/admin

---

## 10. CI/CD (GitHub Actions)

Проект содержит готовый workflow `.github/workflows/ci.yml`, который:

- Запускает тесты на Python 3.10–3.12
- Проверяет безопасность (Bandit)
- Собирает и пушит Docker-образ в Docker Hub при пуше в main

---

## 11. Обновление приложения

### 11.1 Получить новые изменения

```bash
git pull
```

### 11.2 Пересобрать и перезапустить

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

После обновления рекомендуется выполнить миграции БД (делается автоматически в `entrypoint.sh`).

---

## 12. Backup и восстановление

### Автоматические бэкапы

В `docker-compose.prod.yml` включена служба `backups`, которая:

- Делает ежедневный `pg_dump`
- Копирует папку `encrypted/`
- Удаляет старые бэкапы старше 30 дней

### Ручной backup

```bash
docker compose exec db pg_dump -U smdg_user smdg > backup_$(date +%Y%m%d).sql
```

### Backup при использовании S3

При использовании S3 данные уже хранятся в облаке, но рекомендуется:

- Регулярно бэкапить БД (PostgreSQL)
- Настроить S3 Versioning на бакете
- Настроить S3 Lifecycle Policies для автоматического удаления старых версий

---

## 13. Мониторинг

В проекте настроены:

- **Prometheus** (`/metrics`)
- **Grafana** (порт 3000, закрыт снаружи)
- Панель Grafana доступна по пути `/grafana/`

Логи хранятся в `audit_logs/` и в json-формате Docker.

### Мониторинг S3

При использовании S3/MinIO:

- MinIO Console: http://minio:9001 (только с `--profile s3`)
- Метрики хранилища доступны через `/api/stats` endpoint
- S3 bucket size и file count отображаются в статистике системы

---

## 14. Troubleshooting

| Проблема                    | Решение                                                                       |
|-----------------------------|-------------------------------------------------------------------------------|
| Не запускается PostgreSQL   | Проверьте наличие секрета `postgres_password`                                 |
| Ошибка "age.key not found"  | Сгенерируйте ключ: `age-keygen -o secrets/age.key`                            |
| Не работает HTTPS           | Убедитесь, что в `nginx-https.conf` указаны правильные пути к сертификатам    |
| Rate limiter не работает    | Проверьте подключение к Redis (`docker compose logs redis`)                   |
| S3 подключение не работает  | Проверьте `S3_ENDPOINT_URL` и credentials, убедитесь что MinIO запущен (`docker compose --profile s3 ps`) |
| Ошибка "bucket not found"   | Запустите `docker compose run --rm smdg bash /app/scripts/init_s3_buckets.sh` |
| Файлы не загружаются в S3   | Проверьте права доступа к бакету и размер файла (лимит 600MB)                 |

---

## 15. Архитектура хранилища

### Режимы работы

```
┌──────────────────────────────────────────────────────────────┐
│                        SMDG Application                      │
│                                                              │
│  Upload → ClamAV → age Encrypt → StorageBackend → Storage    │
│  Download ← FileResponse ← age Decrypt ← StorageBackend      │
└──────────────────────┬───────────────────────────────────────┘
                       │
          ┌────────────┴────────────┐
          │                         │
   ┌──────▼──────┐          ┌──────▼──────┐
   │ Local FS    │          │  S3/MinIO   │
   │ /encrypted  │          │  Bucket     │
   └─────────────┘          └─────────────┘
```

### Ключевые компоненты

| Компонент               | Описание                               |
|-------------------------|----------------------------------------|
| `StorageBackend` (ABC)  | Абстрактный интерфейс хранилища        |
| `LocalStorageBackend`   | Реализация для локальной ФС            |
| `S3StorageBackend`      | Реализация для S3/MinIO (aiobotocore)  |
| `StorageFactory`        | Фабрика выбора бэкенда по конфигурации |

### Переключение режимов

Переключение происходит **без изменения кода** — только через переменные окружения:

```bash
# Локальный режим (по умолчанию)
S3_ENABLED=false

# S3 режим
S3_ENABLED=true
S3_ENDPOINT_URL=http://minio:9000
```

---

**Готово к использованию.**
