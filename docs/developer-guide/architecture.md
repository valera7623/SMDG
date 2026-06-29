# Архитектура

Обзор архитектуры SMDG для разработчиков.

## Обзор

SMDG — self-hosted система обмена медицинскими файлами с **end-to-end шифрованием** (age), временными ссылками, аудитом и опциональным DICOMweb.

## Высокоуровневая схема

```mermaid
graph TD
    subgraph Client
        A[Web UI / API clients]
    end
    subgraph Edge
        B[Nginx — TLS, routing]
    end
    subgraph SMDGApp[SMDG FastAPI]
        C[REST + DICOMweb routes]
        D[Middleware: tenant, audit, rate limit, SLO, tracing]
        E[Lifespan: keys, Redis, schedulers, DLQ]
    end
    subgraph Data
        F[(PostgreSQL)]
        G[(Redis)]
    end
    subgraph Storage
        H[Local FS or S3]
        I[age-encrypted blobs]
    end

    A --> B --> C
    C --> D
    C --> E
    C --> F
    C --> G
    C --> H
    H --> I
```

## Слои приложения

| Слой | Каталог | Ответственность |
|------|---------|-----------------|
| API | `app/api/` | Upload, download, auth, admin, DICOMweb, health |
| Core | `app/core/` | Config, storage, security, middleware, tracing |
| Services | `app/services/` | Webhooks, archive, DLQ, email/Telegram |
| Models | `app/models/` | SQLModel entities |

## Поток загрузки

1. `POST /api/upload` (authenticated, tenant-scoped).
2. Валидация MIME/размера.
3. Шифрование age → `StorageBackend`.
4. Метаданные в PostgreSQL + audit event.

## Поток скачивания

1. Авторизованный `GET /api/download/{id}` или публичная ссылка.
2. Чтение ciphertext из storage.
3. Расшифровка age → stream клиенту.
4. Audit `file.downloaded`.

## Масштабирование

- Горизонтальное масштабирование за Nginx load balancer.
- Shared PostgreSQL + Redis + S3.
- Stateless FastAPI workers.

Подробнее: [src/ARCHITECTURE.md](../src/ARCHITECTURE.md).

## Безопасность

- Argon2id для паролей, HS256 JWT, TOTP 2FA.
- Docker Secrets для production.
- Rate limiting (slowapi + Redis).

См. [Безопасность](../misc/security.md).
