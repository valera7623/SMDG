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

2. Production запуск

docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d

📁 Структура проекта

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
app/core/audit.py	        Централизованный аудит
app/core/cleanup.py	        Автоматическая очистка

🔐 Безопасность

Все файлы шифруются до записи на диск
Пароли — только Argon2
2FA желательна
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
SECURITY.md	                            Политика безопасности, threat model
COMPLIANCE_TEMPLATE.md	                Шаблон соответствия ФЗ-152/GDPR
TESTING.md	                            Стратегия тестирования, coverage (93%)
TROUBLESHOOTING.md	                    Решение типовых проблем
CHANGELOG.md	                        История версий

🤝 Внесение изменений
Проект находится в приватной разработке. Подробности см. в CONTRIBUTING.md.

📄 Лицензия
Проект распространяется под лицензией MIT.
Автор: Валерий Попов

SMDG — ваш безопасный шлюз для медицинских данных.






