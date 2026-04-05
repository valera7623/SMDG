# API Documentation - Secure Medical Data Gateway (SMDG)

**Версия:** 1.0  
**Дата:** 05 апреля 2026  
**Base URL:** `/api`

---

## 1. Общая информация

- Все запросы (кроме статических файлов) идут через префикс `/api`
- Аутентификация — **JWT-токен в HttpOnly cookie** `access_token`
- Формат ответов — **JSON**
- Rate limiting включён на всех критичных эндпоинтах
- Для загрузки файлов используется `multipart/form-data`

### Аутентификация

Все защищённые эндпоинты требуют наличия cookie `access_token`.  
Токен выдаётся при успешном логине и автоматически отправляется браузером.

**Пример заголовка (если используете Authorization вместо cookie):**
```http
Authorization: Bearer <token>

2. Authentication (/api/auth)
POST /api/auth/register
Регистрация нового пользователя.
Тело запроса (JSON):
JSON{
  "username": "doctor1",
  "email": "doctor1@example.com",
  "password": "StrongPass123!"
}
Ответ:
JSON{
  "message": "Пользователь успешно зарегистрирован",
  "username": "doctor1",
  "email": "doctor1@example.com",
  "role": "user",
  "2fa_enabled": false
}

POST /api/auth/login
Вход в систему.
Тело запроса (form-data):

username
password
otp_code (опционально, если 2FA включён)

Ответ (успех):
JSON{
  "message": "Успешный вход",
  "username": "admin",
  "role": "admin",
  "2fa_enabled": true
}
Cookie access_token устанавливается автоматически (HttpOnly).

POST /api/auth/logout
Выход из системы.
Ответ:
JSON{"message": "Вы успешно вышли из системы"}

POST /api/auth/change-password
Смена пароля (требует авторизации).
Тело (JSON):
JSON{
  "old_password": "OldPass123!",
  "new_password": "NewStrongPass456!",
  "otp_code": "123456"
}

POST /api/auth/setup-2fa
Настройка двухфакторной аутентификации.
Ответ:
JSON{
  "message": "Отсканируйте QR-код...",
  "otp_url": "otpauth://totp/...",
  "instructions": ["1. Откройте приложение...", "..."],
  "warning": "Сохраните этот QR..."
}

POST /api/auth/verify-2fa-setup
Подтверждение настройки 2FA.
Тело (JSON):
JSON{ "code": "123456" }

POST /api/auth/disable-2fa
Отключение 2FA.
Тело (form-data):

otp_code


3. File Management
POST /api/upload
Загрузка и шифрование файла.
Тело (form-data):

file — файл
ttl_days — срок жизни (по умолчанию 30)
max_downloads — максимальное количество скачиваний (по умолчанию 1)
patient_id — ID пациента (опционально)
medical_metadata_json — JSON с метаданными (опционально)

Ответ:
JSON{
  "message": "Файл успешно загружен и зашифрован",
  "original_name": "scan.pdf",
  "download_url": "/api/download?token=xxx-xxx-xxx",
  "expires_at": "2026-05-05T12:00:00Z",
  "max_downloads": 1
}

GET /api/download и POST /api/download
Скачивание файла (по токену или имени).
Query параметры (GET):

token — одноразовый токен

Form (POST):

filename — имя зашифрованного файла (для авторизованных пользователей)

Возвращает файл с оригинальным именем.

GET /api/list
Получить список файлов текущего пользователя.
Ответ:
JSON{
  "count": 5,
  "files": [
    {
      "id": 42,
      "name": "abc123_scan.dcm.age",
      "original_name": "scan.dcm",
      "size": 2457600,
      "patient_id": "P-12345",
      "download_url": "/api/download?token=..."
    }
  ]
}

POST /api/delete-user-file
Удаление своего файла пользователем.
Тело (form-data):

filename
confirm=true


POST /api/delete (только админ)
Удаление любого файла администратором.
Тело (form-data):

filename
confirm=true
reason (опционально)


4. Admin Users Management (/api/admin/users)
Все эндпоинты требуют роли admin.


Метод   Путь                                            Описание

GET     /api/admin/users/                               Список пользователей (с фильтрами и пагинацией)
GET     /api/admin/users/{user_id}                      Информация об одном пользователе
POST    /api/admin/users/                               Создать пользователя    
PUT     /api/admin/users/{user_id}                      Обновить пользователя   
DELETE  /api/admin/users/{user_id}                      Удалить пользователя (?confirm=true)
POST    /api/admin/users/{user_id}/reset-password       Сброс пароля
POST    /api/admin/users/bulk                           Массовые действия
GET     /api/admin/users/stats/overview                 Статистика пользователей

5. Cleanup (/api/cleanup)

GET /api/cleanup/stats — статистика временных файлов
GET /api/cleanup/files — список временных файлов
POST /api/cleanup/force — принудительная полная очистка (decrypted + encrypted)


6. System & Stats

GET /api/stats — полная статистика системы
GET /api/stats/summary — краткая сводка
GET /api/stats/health — детальная проверка здоровья
GET /health — базовая проверка работоспособности
GET /metrics — Prometheus метрики


7. Примеры запросов (cURL)
Логин:
curl -X POST http://localhost/api/auth/login \
  -d "username=admin&password=admin123" \
  -c cookies.txt

Загрузка файла:
curl -X POST http://localhost/api/upload \
  -H "Cookie: access_token=..." \
  -F "file=@scan.pdf" \
  -F "ttl_days=7" \
  -F "max_downloads=1"
  
Скачивание по токену:
curl -X GET "http://localhost/api/download?token=xxx" -c cookies.txt -O

8. Rate Limiting

/api/auth/login — 10 попыток в минуту
/api/upload — 10 файлов в минуту
Большинство эндпоинтов — 100 запросов в минуту