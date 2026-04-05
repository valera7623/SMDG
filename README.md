# Secure Medical Data Gateway (SMDG)

**Безопасная передача медицинских файлов с end-to-end шифрованием**

SMDG — это self-hosted решение для безопасного обмена медицинскими данными между врачами, клиниками и пациентами. Все файлы шифруются на сервере, имеют временные защищённые ссылки и полный аудит действий.

---

## ✨ Основные возможности

- **Полное шифрование файлов** с помощью **age** (asymmetric encryption)
- **Временные одноразовые ссылки** (TTL + ограничение по количеству скачиваний)
- **Антивирусная проверка** через ClamAV перед сохранением
- **Двухфакторная аутентификация** (2FA / TOTP + QR-код)
- **Ролевая модель доступа**: `admin` | `doctor` | `user`
- **Полный аудит всех операций** (JSON + CSV)
- **Автоматическая очистка** старых файлов (APScheduler)
- **Ротация ключей шифрования** с перешифровкой всех файлов
- **Удобный веб-интерфейс** (пользовательский + админ-панель)
- **Rate limiting** и защита от brute-force
- Полная поддержка Docker + Docker Secrets

---

## 🛠️ Технологический стек

- **Backend**: FastAPI + Uvicorn
- **База данных**: PostgreSQL + SQLAlchemy 2 + SQLModel
- **Кэш и rate limiting**: Redis
- **Шифрование**: [age](https://github.com/FiloSottile/age)
- **Антивирус**: ClamAV
- **Аутентификация**: JWT (HttpOnly cookies) + Argon2
- **2FA**: pyotp
- **Задачи**: APScheduler
- **Контейнеризация**: Docker + docker-compose
- **Фронтенд**: Vanilla JS + HTML + CSS

---

## 🚀 Быстрый старт

### 1. Локальный запуск (Development)

```bash
# 1. Клонируйте репозиторий
git clone <ваш-репозиторий>
cd smdg

# 2. Скопируйте переменные окружения
cp .env.example .env

# 3. Запустите через Docker Compose
docker compose up --build

Приложение будет доступно по адресу: http://localhost

2. Production запуск
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# Создать/обновить администратора
poetry run python -m app.cli create-admin admin StrongPass123! admin@example.com

# Ротация ключей шифрования (с перешифровкой всех файлов)
poetry run python -m app.cli rotate-keys --backup-dir /app/backups/keys

smdg/
├── app/                    # Основной код приложения
│   ├── api/                # Эндпоинты (upload, download, auth, admin и т.д.)
│   ├── core/               # Конфигурация, БД, security, cleanup, audit
│   ├── crypto/             # Работа с age
│   ├── models/             # Модели БД (User, File, FileLink)
│   ├── static/             # Фронтенд (HTML, JS, CSS)
│   └── main.py
├── encrypted/              # Зашифрованные файлы
├── decrypted/              # Временные расшифрованные файлы
├── keys/                   # age.key и age.pub
├── audit_logs/             # Логи аудита
├── migrations/             # Alembic миграции
├── docker-compose.yml
├── docker-compose.prod.yml
├── Dockerfile
├── entrypoint.sh
└── pyproject.toml

🔐 Безопасность

Все файлы шифруются до записи на диск
Пароли хранятся только в Argon2
2FA (TOTP) для всех пользователей
Rate limiting на все критичные эндпоинты
Полный аудит действий (кто, что, когда, зачем)
Docker Secrets для хранения чувствительных данных
Автоматическая ротация ключей шифрования


📊 Доступные интерфейсы

Главная страница: http://localhost
Панель администратора: http://localhost/admin
Управление пользователями: http://localhost/admin/users
Здоровье системы: http://localhost/health
Метрики Prometheus: http://localhost/metrics


📄 Лицензия
Проект распространяется под лицензией MIT.
Автор: Валерий Попов

SMDG — ваш безопасный шлюз для медицинских данных.





