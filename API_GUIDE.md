# API Guide — Secure Medical Data Gateway (SMDG)

**Версия:** 1.0  
**Дата:** 06 апреля 2026  

> **📘 Интерактивная документация**
>
> Полная спецификация всех эндпоинтов, параметров, форматов запросов и ответов доступна в формате OpenAPI:
> - **Swagger UI:** `/docs` (после запуска приложения)
> - **ReDoc:** `/redoc` (после запуска приложения)
> - **OpenAPI JSON:** `/openapi.json`
>
> Данный документ описывает **общие принципы работы с API**, **правила аутентификации**, **бизнес-логику** и **особенности**, которые не отражены в автоматической спецификации.

"Полная спецификация admin-эндпоинтов доступна исключительно в Swagger UI (/docs)."


---

## Содержание

1. [Базовые принципы](#1-базовые-принципы)
2. [Аутентификация и авторизация](#2-аутентификация-и-авторизация)
3. [Форматы данных и ограничения](#3-форматы-данных-и-ограничения)
4. [Обработка ошибок](#4-обработка-ошибок)
5. [Rate Limiting](#5-rate-limiting)
6. [Бизнес-правила и особенности](#6-бизнес-правила-и-особенности)
7. [Потоки данных (Sequence Diagrams)](#7-потоки-данных-sequence-diagrams)
8. [Security Headers](#8-security-headers)
9. [DICOM API](#9-dicom-api)

---

## 1. Базовые принципы

### 1.1. Base URL
/api

### 1.2. Форматы
| Тип               | Формат                     |
|-------------------|----------------------------|
| Запросы (обычные) | `application/json`         |
| Загрузка файлов   | `multipart/form-data`      |
| Ответы            | `application/json`         |
| Скачивание файлов | `application/octet-stream` |

### 1.3. Кодировка
- Все текстовые данные: **UTF-8**
- Имена файлов: URL-encoded при передаче

### 1.4. Версионирование
API версионируется через URL (`/api/`).  
Breaking changes будут сопровождаться увеличением мажорной версии и публикацией миграционного гайда.

---

## 2. Аутентификация и авторизация

### 2.1. Основной способ — HttpOnly Cookie

```http
Set-Cookie: access_token=<JWT>; HttpOnly; Secure; SameSite=Lax; Path=/

Характеристики:

Параметр	          Значение
Имя cookie	        access_token
Алгоритм JWT	      HS256
Время жизни	        60 минут
HttpOnly	          ✅ (недоступен из JavaScript)
Secure	            ✅ (только по HTTPS)
SameSite	          Lax

Получение cookie:
POST /api/auth/login
Content-Type: application/x-www-form-urlencoded
username=admin&password=secret
При успешном входе cookie устанавливается автоматически.

### 2.2. Альтернативный способ — Bearer Token
Для внешних интеграций (мобильные приложения, сервисы):

GET /api/list
Authorization: Bearer <jwt_token>

### 2.3. Ролевая модель

Роль	    Права
admin	    Полный доступ: управление пользователями, очистка системы, просмотр всей статистики
doctor	  Загрузка/скачивание файлов, просмотр своих файлов, смена пароля
user	    Базовые операции (зависит от конфигурации)

Проверка роли в заголовках ответа:
X-User-Role: admin
X-User-Id: 42

### 2.4. Двухфакторная аутентификация (2FA)

Согласно политике безопасности проекта (см. SECURITY.md):
- 2FA (TOTP) является обязательной рекомендацией для всех пользователей.
- После первой успешной авторизации пользователю рекомендуется немедленно настроить двухфакторную аутентификацию.
- Для администраторов (admin) использование 2FA обязательно.

Для пользователей с включённой 2FA:
    При логине обязателен параметр otp_code
    Код генерируется TOTP (30 секунд, 6 цифр)
    Поддерживаются все стандартные аутентификаторы (Google Authenticator, Authy, 1Password)

Доступные операции с 2FA:

Метод       Эндпоинт                           Описание                           Требуется OTP 
POST        /api/auth/setup-2fa                Генерация QR-кода для настройки    Нет
POST        /api/auth/verify-2fa-setup         Подтверждение настройки 2FA        Да
POST        /api/auth/disable-2fa              Отключение 2FA                     Да

Отключение 2FA

POST /api/auth/disable-2fa

Тело запроса (form-data):

otp_code — 6-значный код из приложения-аутентификатора (обязательно)

Пример запроса:

POST /api/auth/disable-2fa
Content-Type: application/x-www-form-urlencoded

otp_code=123456
Ответы:
200 OK — 2FA успешно отключена
400 Bad Request — неверный или отсутствующий код
401 Unauthorized — неверный код 2FA
404 Not Found — пользователь не найден

Важно: 
При смене пароля 2FA автоматически отключается (требуется повторная настройка) чтобы исключить захват аккаунта через смену пароля без повторной верификации второго фактора.
Отключение 2FA возможно только с подтверждением текущим кодом из приложения.

## 3. Форматы данных и ограничения

### 3.1. Поля с особыми правилами

Поле                    Формат    	    Пример	                Правила
username	              string	        doctor_ivanov	          3-50 символов, только a-z0-9_-
password	              string	        —	                      минимум 8 символов, 1 цифра, 1 спецсимвол
patient_id	            string	        P-12345	                Опционально, свободный формат
medical_metadata_json	  JSON string	    {"diagnosis": "I10"}	  Экранированный JSON, макс. 4096 байт
ttl_days	              integer	        30	                    1–365, по умолчанию 30
max_downloads	          integer	        3	                      1–100, по умолчанию 1

### 3.2. Ограничения на файлы

Параметр	                            Значение
Максимальный размер	                  50 MB
Разрешённые MIME-типы	                application/pdf, image/jpeg, image/png, application/dicom, text/plain
Разрешённые расширения	              .pdf, .jpg, .jpeg, .png, .dcm, .txt
Проверка	                            ClamAV (обязательно), libmagic (MIME)

### 3.3. Формат audit_id

Некоторые эндпоинты возвращают audit_id для отслеживания операции:
{
  "audit_id": "550e8400-e29b-41d4-a716-446655440000",
  "message": "Файл загружен"
}
Используйте этот ID при обращении в службу поддержки.

## 4. Обработка ошибок

### 4.1. Структура ответа с ошибкой

{
  "detail": "Человекочитаемое описание ошибки"
}

### 4.2. Коды статусов

Код	                Название	              Когда возникает
200	                OK	                    Успешный запрос
400	                Bad Request	            Неверный формат, вирус, недопустимый тип файла
401	                Unauthorized	          Отсутствует или неверный токен
403	                Forbidden	              Недостаточно прав (роль не подходит)
404	                Not Found	              Пользователь/файл/токен не найден
409	                Conflict	              Попытка создать существующего пользователя
410	                Gone	                  Ссылка истекла или лимит скачиваний исчерпан
413	                Payload Too Large	      Файл превышает 50 MB
429	                Too Many Requests	      Превышен rate limit
500	                Internal Server Error	  Ошибка сервера (логируются автоматически)
503	                Service Unavailable	    ClamAV недоступен (только production)

### 4.3. Специфические ошибки

Ошибка валидации (400)

{
  "detail": [
    {
      "loc": ["body", "username"],
      "msg": "field required",
      "type": "value_error.missing"
    }
  ]
}
Вирус обнаружен (400)
{
  "detail": "Обнаружен вредоносный код: Eicar-Test-Signature"
}

Rate Limit (429)
{
  "detail": "Слишком много попыток. Попробуйте позже (лимит: 10 запросов в минуту)"
}

ClamAV недоступен (503)
{
  "detail": "Антивирусный сервис недоступен"
}

Специальная ошибка для смены пароля (400)
{
  "detail": "change-password"
}

Возвращается при попытке администратора изменить свой аккаунт через admin-эндпоинты. Фронтенд должен перенаправить пользователя на форму смены пароля.

## 5. Rate Limiting

### 5.1. Лимиты по умолчанию

Тип эндпоинтов	                        Лимит	            Окно
Аутентификация (/auth/login)	          5 попыток	        5 минут
Загрузка файлов (/upload)	              10 запросов	      1 минута
Скачивание (/download)	                20 запросов	      1 минута
Админские операции	                    30 запросов	      1 минута
Остальные	                              60 запросов	      1 минута

### 5.2. Заголовки rate limit

При каждом запросе возвращаются:

X-RateLimit-Limit: 10
X-RateLimit-Remaining: 7
X-RateLimit-Reset: 1617181723
Retry-After: 42

### 5.3. Исключения
Healthcheck (/health) — без лимитов
Метрики (/metrics) — без лимитов (но доступны только с localhost в production)

## 6. Бизнес-правила и особенности

### 6.1. Работа с пользователями (Admin API)

Правило 1: Нельзя применять массовые операции к себе

POST /api/admin/users/bulk
{
  "user_ids": [42],  # 42 — ID текущего администратора
  "action": "deactivate"
}
→ 400 Нельзя применять массовые операции к своей учётной записи

Правило 2: Нельзя деактивировать/удалять других администраторов

POST /api/admin/users/bulk
{
  "user_ids": [1, 7],  # оба — admin
  "action": "deactivate"
}
→ 400 Нельзя деактивировать администраторов

Правило 3: Смена роли администратора запрещена

POST /api/admin/users/bulk
{
  "user_ids": [1],
  "action": "change_role",
  "role": "doctor"
}
→ 400 Нельзя изменить роль администраторов

Правило 4: Массовое удаление требует подтверждения

DELETE /api/admin/users/42?confirm=true
Параметр confirm обязателен для action=delete.

### 6.2. Работа с файлами

Одноразовые ссылки:
Создаются автоматически при загрузке файла
Ссылка действительна до наступления expires_at ИЛИ пока downloads_count < max_downloads
После исчерпания лимита → статус 410

TTL (Time To Live):
Зашифрованные файлы хранятся ttl_days дней
По истечении TTL удаляются фоновым cleanup-сервисом
Пользователь не может "продлить" TTL после загрузки

Медицинские метаданные:

{
  "patient_id": "P-12345",
  "patient_name": "Иванов И.И.",
  "diagnosis_code": "I10",
  "study_date": "2026-04-05",
  "modality": "CT",
  "notes": "Контрольное обследование"
}
Поле medical_metadata_json принимает строку с JSON, не объект.

### 6.3. Cleanup и временные файлы

Тип файлов	                    Расположение	            TTL	                Механизм очистки
Расшифрованные (временные)	    /decrypted/	              1 час	              APScheduler (каждые 15 минут)
Зашифрованные	                  /encrypted/	              ttl_days	          Ежедневно
Аудит-логи	                    /audit_logs/	            365 дней	          Еженедельно
Токены в БД	                    file_links	              24 часа + лимит	    При каждом запросе + фоновая задача

Принудительная очистка (только admin):

POST /api/cleanup/force

### 6.4. Аудит

Все действия логируются с:
ID пользователя
IP-адрес (из X-Forwarded-For)
Timestamp (UTC)
Результат операции (успех/ошибка)
Audit ID (UUID)

Доступ к логам:
Через файловую систему (/audit_logs/)
Для администраторов — через API (будет в версии 1.1)

Важное примечание:
Скачивание по публичной одноразовой ссылке (GET /api/download?token=...) в текущей версии не логируется в систему аудита.
Аудит выполняется только при скачивании авторизованным пользователем (POST /api/download).

## 7. Потоки данных (Sequence Diagrams)

### 7.1. Загрузка файла с проверкой ClamAV

Клиент → API: POST /upload (file, metadata)
API → ClamAV: сканирование потока
ClamAV → API: CLEAN / FOUND

Если FOUND:
  API → Клиент: 400 Virus detected + audit log

Если CLEAN:
  API → Crypto: encrypt_file()
  Crypto → Storage: сохранить .age
  API → DB: INSERT INTO files, file_links
  API → Клиент: 200 + download_url

### 7.2. Скачивание по одноразовой ссылке

sequenceDiagram
    participant Client
    participant FastAPI
    participant DB
    participant Storage
    participant Crypto

    Client->>FastAPI: GET /api/download?token=xxx
    FastAPI->>DB: find FileLink by token
    alt Token valid
        DB-->>FastAPI: File record
        FastAPI->>Storage: get encrypted file
        FastAPI->>Crypto: decrypt_file()
        Crypto-->>FastAPI: decrypted bytes
        
        Note over FastAPI,DB: Критический участок — гарантия "at-least-once"
        FastAPI->>DB: increment downloads_count<br/>и/или delete link (если лимит исчерпан)
        FastAPI->>DB: commit
        
        FastAPI-->>Client: FileResponse (streaming)
        FastAPI->>Background: delete temporary file (after response)
        
        Note right of FastAPI: Аудит **не логируется** при скачивании по публичному токену<br/>(текущее поведение)
    else Invalid/Expired
        FastAPI-->>Client: 404 / 410
    end

### 7.3. Логин с 2FA

Клиент → API: POST /auth/login (username, password, otp_code?)
API → DB: SELECT user WHERE username = ?

Если user.disabled:
  API → Клиент: 401 Account disabled

Если otp_secret существует:
  API → OTP: verify(otp_code, otp_secret)
  Если неверно:
    API → Клиент: 400 Требуется код 2FA / Неверный код

Если 2FA пройдена или не требуется:
  API → Security: create_jwt(user.id, user.role)
  API → Клиент: 200 + Set-Cookie: access_token=...

## 8. Security Headers

Все ответы API содержат следующие заголовки (в production):

Strict-Transport-Security: max-age=31536000; includeSubDomains
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Content-Security-Policy: default-src 'self'
Cache-Control: no-store, no-cache, must-revalidate

## 9. DICOM API

### 9.1 Обзор

DICOM API — подсистема просмотра медицинских изображений.
Все эндпоинты (кроме `/dicom/view-url`) авторизуются через **view_token** — временный UUID.

### 9.2 Основные эндпоинты

| Метод   | Путь                                    | Auth       | Описание                    |
|---------|-----------------------------------------|------------|-----------------------------|
| `POST`  | `/api/dicom/view-url?file_id=N`         | JWT cookie | Генерация view-токена       |
| `GET`   | `/api/dicom/render/{file_id}?token=T`   | view_token | DICOM → PNG (pydicom+numpy) |
| `GET`   | `/api/dicom/metadata/{file_id}?token=T` | view_token | DICOM-теги → JSON (Redis)   |
| `GET`   | `/api/dicom/wado/{file_id}?token=T`     | view_token | DICOM streaming             |

### 9.3 QIDO-RS (DICOMweb Query)

| Метод   | Путь                                      | Auth       | Описание           |
|---------|-------------------------------------------|------------|--------------------|
| `GET`   | `/api/dicom/qido/studies?token=T`         | view_token | Список исследований|
| `GET`   | `/api/dicom/qido/studies/{uid}/series`    | view_token | Серии              |
| `GET`   | `/api/dicom/qido/.../instances`           | view_token | Экземпляры         |

**Параметры QIDO-RS:** `fuzzymatching`, `includefield` (по умолчанию `all`), `limit`.

### 9.4 WADO-RS (DICOMweb Retrieve)

| Метод   | Путь                                                    | Auth       | Описание      |
|---------|---------------------------------------------------------|------------|---------------|
| `GET`   | `/api/dicom/wado/studies/{s}/series/{se}/instances/{i}?token=T` | view_token | DICOM объект |

### 9.5 Формат QIDO-RS ответов

Стандартный DICOM JSON:
```json
{
  "00080060": { "vr": "CS", "Value": ["CT"] },
  "0020000D": { "vr": "UI", "Value": ["2.25.607865..."] },
  "00100010": { "vr": "PN", "Value": [{"Alphabetic": "Иванов^Иван"}] }
}
```

### 9.6 Redis-кэш

Метаданные DICOM кэшируются в Redis (`smdg:dicom_meta:{file_id}`, TTL 2.25 часа).
Первый запрос: расшифровка → pydicom → кэш. Повторные: мгновенно из Redis.

### 9.7 Безопасность

- Расшифрованные данные **никогда не записываются на диск**
- View-токен: UUID v4, TTL 15 мин (настраивается), привязан к file_id
- Feature Flag: `DICOM_VIEWER_ENABLED=false` → все DICOM-эндпоинты возвращают 501

---

## 10. Ссылки

Ресурс	                    URL	                            Описание
Swagger UI	                /docs	                          Интерактивная документация
ReDoc	                      /redoc	                        Альтернативный просмотр
OpenAPI JSON	              /openapi.json	                  Машинно-читаемая спецификация
Healthcheck	                /health	                        Статус сервиса
Prometheus metrics	        /metrics	                      Метрики для мониторинга
Grafana (если включена)	    /grafana/	                      Дашборды

## 11. Changelog API

Версия	            Дата	            Изменения
1.0	                2026-04-06	      Стабильный релиз
1.1	                2026-04-10	      Audit API, Webhook-уведомления, S3 storage
3.0	                2026-04-12	      DICOM Viewer, QIDO-RS, WADO-RS, Redis cache



Конец документа.