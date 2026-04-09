# DEPLOYMENT.md

**Secure Medical Data Gateway (SMDG)** — Руководство по развертыванию

**Версия:** 1.0  
**Дата:** 05 апреля 2026

---

## 1. Обзор

SMDG полностью контейнеризирован и разворачивается через **Docker Compose**.  
Поддерживаются два режима:

- **Development** — для локальной разработки и тестирования
- **Production** — для боевого окружения (рекомендуемый)

Используется многоуровневая конфигурация:
- `docker-compose.yml` (базовый)
- `docker-compose.prod.yml` (переопределения для продакшена)

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

## 4. Подготовка секретов (обязательно!)
Создайте папку secrets/ и положите туда файлы:
Bashmkdir -p secrets

# Генерация необходимых секретов
echo "your-super-strong-jwt-secret-key-min-48-chars" > secrets/jwt_secret.txt
echo "ChangeMe123!StrongPasswordForAdmin" > secrets/admin_password.txt
echo "your-postgres-password-here" > secrets/postgres_password.txt
echo "StrongGrafanaPass123!" > secrets/grafana_password.txt

# Ключ age (если нет — будет создан автоматически при первом запуске)
# Рекомендуется сгенерировать заранее:
age-keygen -o secrets/age.key
chmod 600 secrets/age.key
Важно: Никогда не коммитьте папку secrets/ в Git!

## 5. Настройка окружения
Development (.env)
Bashcp .env.example .env

# Отредактируйте .env под себя
Production (.env.prod)
Создайте файл .env.prod:
DOCKER_USERNAME=<your-docker-username>
IMAGE_TAG=latest
DOMAIN=<your-domain>
REDIS_PASSWORD=<your-redis-password>

## 6. Запуск
### 6.1 Development режим
Bashdocker compose up --build -d
Приложение будет доступно по http://localhost
### 6.2 Production режим (рекомендуется)
Первый запуск (сборка образа)
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build

# Последующие запуски
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
Приложение будет доступно по HTTPS через Nginx.

## 7. После первого запуска

Проверьте логи:Bashdocker compose logs -f smdg
Создайте первого администратора (если не создан автоматически):Bashdocker compose exec smdg python -m app.cli create-admin \<admin-username> <strong-password> <admin@your-domain.com>
Проверьте работоспособность:
http://ваш-домен/health
http://ваш-домен/admin



## 8. CI/CD (GitHub Actions)
Проект содержит готовый workflow .github/workflows/ci.yml, который:

Запускает тесты на Python 3.10–3.12
Проверяет безопасность (Bandit)
Собирает и пушит Docker-образ в Docker Hub при пуше в main


## 9. Обновление приложения
### 9.1 Получить новые изменения
git pull

### 9.2 Пересобрать и перезапустить
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
После обновления рекомендуется выполнить миграции БД (делается автоматически в entrypoint.sh).

## 10. Backup и восстановление
Автоматические бэкапы
В docker-compose.prod.yml включена служба backups, которая:

Делает ежедневный pg_dump
Копирует папку encrypted/
Удаляет старые бэкапы старше 30 дней

Ручной backup
Bashdocker compose exec db pg_dump -U smdg_user smdg > backup_$(date +%Y%m%d).sql

## 11. Мониторинг
В проекте настроены:

Prometheus (/metrics)
Grafana (порт 3000, закрыт снаружи)
Панель Grafana доступна по пути /grafana/

Логи хранятся в audit_logs/ и в json-формате Docker.

## 12. Troubleshooting
Проблема: Не запускается PostgreSQL
Решение: Проверьте наличие секрета postgres_password
Проблема: Ошибка "age.key not found"
Решение: Сгенерируйте ключ: age-keygen -o secrets/age.key
Проблема: Не работает HTTPS
Решение: Убедитесь, что в nginx-https.conf указаны правильные пути к сертификатам
Проблема: Rate limiter не работает
Решение: Проверьте подключение к Redis (docker compose logs redis)

Готово к использованию.