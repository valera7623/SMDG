# TROUBLESHOOTING.md

**Secure Medical Data Gateway (SMDG)** — Руководство по устранению неисправностей

**Версия:** 1.0  
**Дата:** 05 апреля 2026

---

## 1. Как быстро собрать диагностику

Перед тем, как искать проблему, выполните эти команды:

```bash
# 1. Логи всех сервисов
docker compose logs -f --tail=100

# 2. Логи только основного приложения
docker compose logs smdg --tail=200

# 3. Статус всех контейнеров
docker compose ps -a

# 4. Проверка здоровья
curl -I http://localhost/health

2. Частые проблемы и решения
2.1. Docker / Запуск не работает
Ошибка: ports are already allocated
Решение:
docker compose down
docker compose up -d

Ошибка: secret file not found
Решение: Убедитесь, что папка secrets/ существует и содержит все файлы:

jwt_secret.txt
admin_password.txt
postgres_password.txt
age.key
grafana_password.txt

Ошибка: permission denied при запуске

Решение:
chmod 600 secrets/*
chmod +x entrypoint.sh

2.2. PostgreSQL не запускается

Симптом: Контейнер db в статусе restarting или exited
Решение:
docker compose logs db
Чаще всего проблема в отсутствии секрета postgres_password.
Создайте его заново:
echo "StrongPostgresPass123!" > secrets/postgres_password.txt
docker compose down
docker compose up -d db
2.3. Redis не работает / Rate limiter не работает
Симптом: Ошибки Redis connection failed или 429 Too Many Requests
Решение:
docker compose logs redis
docker compose restart redis
2.4. ClamAV не отвечает
Симптом: При загрузке файла ошибка "Антивирусный сервис временно недоступен"
Решение:
docker compose logs clamav
docker compose restart clamav
ClamAV может долго запускаться при первом старте (обновление баз сигнатур).
2.5. Проблемы с ключами age
Ошибка: age.key not found или Публичный ключ не инициализирован
Решение:

mkdir -p secrets keys
age-keygen -o secrets/age.key
cp secrets/age.key keys/age.key
chmod 600 keys/age.key secrets/age.key

docker compose restart smdg
Ошибка при ротации ключей:
Выполните команду вручную:
docker compose exec smdg python -m app.cli rotate-keys
2.6. Проблемы с аутентификацией / Логином
Не работает вход:

Проверьте, что JWT_SECRET_KEY длинный и сложный
Удалите старые cookies в браузере
Проверьте логи: docker compose logs smdg | grep -i auth

2FA не работает:

Убедитесь, что вы сканируете QR-код именно в приложении-аутентификаторе
При смене пароля 2FA автоматически сбрасывается

2.7. Не загружаются файлы
Ошибка 413 (Payload Too Large):
Увеличьте MAX_UPLOAD_SIZE_MB в .env и перезапустите.
ClamAV блокирует файл:
Проверьте логи ClamAV.
Файл не шифруется:
Проверьте наличие и права на keys/age.key.

2.8. Проблемы в Production-режиме
Ошибка: DEV_MODE=true в продакшене
Решение: В файле .env.prod убедитесь, что стоит DEV_MODE=false
Nginx возвращает 502 Bad Gateway:
docker compose logs nginx
docker compose logs smdg

3. Полезные команды
# Перезапустить только приложение
docker compose restart smdg

# Полные логи с метками времени
docker compose logs -f -t smdg

# Войти в контейнер приложения
docker compose exec smdg bash

# Проверить миграции БД
docker compose exec smdg alembic current

# Принудительная очистка временных файлов
docker compose exec smdg python -m app.cli cleanup-force

4. Куда смотреть логи

Приложение: docker compose logs smdg
Аудит: папка audit_logs/ (файлы audit_YYYY-MM-DD.log и audit.csv)
PostgreSQL: docker compose logs db
Redis: docker compose logs redis
ClamAV: docker compose logs clamav


Если проблема не решена — создайте Issue с обязательным приложением:

Вывод docker compose ps -a
Последние 100 строк логов docker compose logs smdg --tail=100
Описание действий, которые привели к ошибке