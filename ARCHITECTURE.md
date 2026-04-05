# Architecture Document

**Secure Medical Data Gateway (SMDG)**  
**Версия:** 1.0  
**Дата:** 05 апреля 2026

---

## 1. Обзор архитектуры

SMDG — это **self-hosted** веб-приложение для безопасной передачи медицинских файлов с акцентом на **конфиденциальность, аудит и соответствие требованиям защиты персональных данных** (в т.ч. ФЗ-152).

### Основные принципы архитектуры:
- **Максимальная безопасность** (zero-trust подход)
- **Разделение ответственности** (Layered Architecture)
- **Асинхронность** (asyncio + FastAPI)
- **Полная контейнеризация** (Docker-first)
- **Готовность к продакшену** (secrets, health checks, monitoring)

---

## 2. Высокоуровневая архитектура

```mermaid
graph TD
    subgraph Client
        A[Веб-интерфейс HTML/JS]
    end

    subgraph "Nginx (Reverse Proxy)"
        B[HTTPS + HTTP/2]
    end

    subgraph "SMDG Application"
        C[FastAPI]
        D[Middleware: Audit + Rate Limit + User Context]
        E[Lifespan Events]
    end

    subgraph "Core Services"
        F[PostgreSQL]
        G[Redis]
        H[ClamAV]
    end

    subgraph "Storage & Crypto"
        I[Encrypted Files]
        J[Age Encryption]
        K[Temporary Decrypted Files]
    end

    A --> B --> C
    C --> D
    C --> E
    C --> F
    C --> G
    C --> H
    C --> I
    C <--> J
    C --> K

3. Компоненты и слои
3.1. Presentation Layer

app/main.py — входная точка приложения
app/api/ — все REST эндпоинты
Фронтенд: static/ (HTML + Vanilla JS + CSS)

3.2. Application Layer

Dependency Injection через FastAPI Depends
Rate Limiting (slowapi + Redis)
Аудит (AuditMiddleware + audit_logger)
Авторизация (get_current_user, get_current_admin, get_current_doctor)

3.3. Domain / Business Logic Layer

app/core/ — основная бизнес-логика
app/crypto/crypto.py — шифрование/расшифровка
app/core/cleanup.py — политика очистки
app/core/storage.py — управление временными файлами

3.4. Data Access Layer

app/core/database.py — Async SQLAlchemy
app/models/ — SQLModel модели (User, File, FileLink)
Alembic миграции (migrations/)

3.5. Infrastructure Layer

Docker + docker-compose
PostgreSQL, Redis, ClamAV
Volume mounts для encrypted/, keys/, audit_logs/


4. Ключевые механизмы
4.1. Шифрование файлов

Используется age (asymmetric)
Публичный ключ хранится в keys/age.pub
Приватный ключ (age.key) защищён и монтируется через Docker Secret
Шифрование происходит до сохранения на диск (upload.py)
Расшифровка — только по запросу (download.py)

4.2. Временные одноразовые ссылки

Модель FileLink (токен + max_downloads + expires_at)
После исчерпания лимита или срока — ссылка автоматически инвалидируется

4.3. Автоматическая очистка

FileCleanupManager + APScheduler
Запускается каждые 30 минут
Разные политики удержания по типам файлов

4.4. Ротация ключей

Команда rotate-keys
Перешифровывает все существующие файлы
Старый ключ автоматически бэкапится

4.5. Аудит

AuditMiddleware логирует все HTTP-запросы
audit_logger.log_operation() — централизованный логгер
Два формата: JSON (по дням) + CSV (для анализа)


5. Lifespan Events (main.py)
При старте приложения выполняются:

init_keys() — инициализация/проверка ключей age
Проверка подключения к Redis
Запуск cleanup_manager.start_cleanup_task()
Создание первого администратора (в dev-режиме)


6. Безопасность (Security Architecture)

Хранение паролей: Argon2 (passlib)
Сессии: JWT в HttpOnly cookie
2FA: TOTP (pyotp) + обязательная проверка
Rate Limiting: SlowAPI + Redis
Middleware: Audit + User Context + Rate Limit
Docker Secrets: все чувствительные данные
CORS: настроен с явным whitelist в продакшене


7. Deployment Architecture
Production использует:

docker-compose.prod.yml (ресурсные лимиты, логирование json-file, отключение лишних портов)
Nginx как reverse proxy + SSL termination
Docker Secrets для всех ключей и паролей
Отдельные volumes: smdg_keys, smdg_encrypted, smdg_audit_logs


8. Ключевые технические решения

Решение                     Почему выбрано
age вместо PyCryptodome     Простота, надёжность, современный стандарт
Asyncio + FastAPI           Высокая производительность
APScheduler вместо Celery   Простота и отсутствие RabbitMQ
Docker Secrets              Соответствие лучшим практикам
Alembic + SQLModel          Удобство миграций и типизация



9. Будущие расширения (Roadmap)

Поддержка S3/MinIO как backend хранения
Multi-tenancy (организации/клиники)
Webhook-уведомления
DICOM viewer в браузере
Экспорт аудита в PDF/Excel
Интеграция с внешними системами (ЕГИСЗ, МИС)


Документ актуален на момент анализа кода (05.04.2026).
Готов обновить или дополнить любую секцию.