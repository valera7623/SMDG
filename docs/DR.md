# Disaster Recovery Plan - SMDG

Версия документа: 1.0  
Дата обновления: 2026-04-22  
Система: SMDG (Secure Medical Data Gateway), версия 4.0.0

## 1. Цели и область

Этот план описывает восстановление SMDG после аварий, влияющих на доступность, целостность и безопасность:

- `smdg` (FastAPI)
- `db` (PostgreSQL)
- `redis`
- `minio`/S3-хранилище
- шифровальные ключи (`age.key`, секреты)
- сетевые компоненты (`nginx`, Docker/Compose)

Ключевые SLO DR:

- Минимизация простоя (RTO)
- Минимизация потери данных (RPO)
- Подтверждаемое восстановление через тесты и чек-листы

## 2. Команда реагирования

| Роль | Имя | Контакт | Зона ответственности |
|------|-----|---------|----------------------|
| Incident Commander | TBD | TBD | Координация DR, эскалации |
| Database Specialist | TBD | TBD | PostgreSQL, WAL, бэкапы |
| Storage Specialist | TBD | TBD | MinIO/S3, целостность объектов |
| Security Specialist | TBD | TBD | Компрометации, ротация ключей |
| Platform Engineer | TBD | TBD | Docker/Compose, хост, сеть |

## 3. Целевые метрики восстановления

| Сценарий | RTO | RPO | Приоритет |
|----------|-----|-----|-----------|
| Отказ одного контейнера | 5 минут | 0 | P1 |
| Отказ базы данных | 30 минут | 5 минут | P1 |
| Отказ S3/MinIO хранилища | 1 час | 15 минут | P1 |
| Потеря ключей шифрования | 2 часа | 0 | P0 |
| Полный отказ сервера | 4 часа | 1 час | P0 |
| Коррупция данных | 2 часа | 15 минут | P0 |
| Компрометация системы | 2 часа | N/A | P0 |
| Отказ Docker/оркестратора | 30 минут | 0 | P1 |

## 4. Артефакты восстановления

- Бэкап БД: `backups/smdg/db_*.sql.gz`
- Бэкап encrypted-данных: `backups/smdg/encrypted/`
- Бэкап конфигурации: `.env`, `docker-compose*.yml`, `secrets/`
- Бэкап ключей: `backups/smdg/age.key_*.gpg`
- Аудит-логи: `backups/smdg/audit_*.tar.gz`
- Манифест: `backups/smdg/manifest_*.txt`
- Актуальный указатель: `backups/smdg/manifest_latest.txt`

## 5. Стандартная процедура DR

1. Объявить инцидент и назначить Incident Commander.
2. Зафиксировать таймстемп начала инцидента.
3. Изолировать затронутый компонент (при компрометации — изоляция сети/доступов).
4. Выбрать runbook по сценарию.
5. Выполнить восстановление (автоматическое или ручное).
6. Подтвердить целостность:
   - `curl -f http://localhost:8000/health/live`
   - `curl -f http://localhost:8000/health/ready`
   - smoke-тест API
7. Зафиксировать RTO/RPO фактические значения.
8. Пост-инцидентный отчёт и корректирующие действия.

## 6. Процедуры восстановления

### 6.1 PostgreSQL

```bash
# Шаг 1: Остановить приложение
 docker compose stop smdg

# Шаг 2: Поднять db, если не поднята
 docker compose up -d db

# Шаг 3: Восстановить из бэкапа
 gunzip -c /backups/smdg/db_<TIMESTAMP>.sql.gz | \
   docker compose exec -T db psql -U smdg_user -d smdg

# Шаг 4: Проверить целостность
 docker compose exec db psql -U smdg_user -d smdg -c "SELECT COUNT(*) FROM users;"

# Шаг 5: Запустить приложение
 docker compose start smdg
```

### 6.2 S3/MinIO (зашифрованные файлы)

```bash
# Шаг 1: Восстановить объекты из бэкапа
aws s3 sync /backups/smdg/encrypted/ s3://smdg-encrypted/ --delete

# Шаг 2: Проверить целостность объектов
python scripts/verify_file_integrity.py --bucket smdg-encrypted

# Шаг 3: Синхронизировать метаданные в БД
python scripts/sync_storage_metadata.py
```

### 6.3 Ключи шифрования

```bash
# Шаг 1: Получить ключ из защищённого хранилища/бэкапа
# HashiCorp Vault / AWS Secrets Manager / офлайн-сейф

# Шаг 2: Разместить ключ
cp /secure/backup/age.key ./keys/age.key
chmod 600 ./keys/age.key

# Шаг 3: Проверить ключ
age --decrypt --identity ./keys/age.key ./encrypted/test.age > /dev/null

# Шаг 4: Ротация ключей при компрометации
docker compose exec smdg python -m app.cli rotate-keys
```

### 6.4 Полный отказ сервера

```bash
# 1) Поднять новый сервер, восстановить код/compose-файлы
# 2) Восстановить секреты и ключи
# 3) Развернуть хранилище (MinIO/S3 endpoint)
# 4) Выполнить полное восстановление
./scripts/restore.sh /backups/smdg/manifest_latest.txt

# 5) Проверка сервиса
curl -f http://localhost:8000/health/ready
```

## 7. Runbook-индекс

- `docs/runbooks/container-failure.md`
- `docs/runbooks/database-failure.md`
- `docs/runbooks/storage-failure.md`
- `docs/runbooks/key-loss-or-compromise.md`
- `docs/runbooks/full-server-failure.md`
- `docs/runbooks/data-corruption.md`
- `docs/runbooks/system-compromise.md`
- `docs/runbooks/docker-orchestrator-failure.md`

## 8. Checklists по сценариям

### 8.1 Отказ контейнера

- [ ] Подтвержден статус `unhealthy/exited`
- [ ] Выполнен `docker compose restart <service>`
- [ ] Проверены зависимости сервиса
- [ ] Пройден `/health/ready`
- [ ] RTO уложился в 5 минут

### 8.2 Отказ БД

- [ ] Подтверждён сбой `pg_isready`
- [ ] Выполнен restart или restore
- [ ] Проверена целостность критических таблиц
- [ ] Проверен API smoke-test
- [ ] RTO <= 30 мин, RPO <= 5 мин

### 8.3 Отказ S3/MinIO

- [ ] Проверена доступность endpoint
- [ ] Выполнен sync из backup
- [ ] Проверены checksum/metadata
- [ ] Проверены загрузка/скачивание файлов
- [ ] RTO <= 1 час, RPO <= 15 мин

### 8.4 Потеря ключей

- [ ] Извлечён резервный ключ из безопасного хранилища
- [ ] Права на ключ `600`
- [ ] Дешифрование тестового файла успешно
- [ ] При риске утечки запущена ротация ключей
- [ ] RTO <= 2 часа, RPO = 0

### 8.5 Полный отказ сервера

- [ ] Подготовлен новый хост и сеть
- [ ] Восстановлены `.env`, `secrets`, `keys`
- [ ] Выполнен `restore.sh`
- [ ] Подтверждены health/readiness и бизнес-флоу
- [ ] RTO <= 4 часа, RPO <= 1 час

### 8.6 Коррупция данных

- [ ] Идентифицирован диапазон повреждения
- [ ] Восстановление на временный стенд
- [ ] Валидация данных и выбор точки восстановления
- [ ] Переключение на восстановленный инстанс
- [ ] RTO <= 2 часа, RPO <= 15 мин

### 8.7 Компрометация системы

- [ ] Изоляция сети/доступа завершена
- [ ] Компрометированные секреты отозваны
- [ ] Проведена ротация ключей и паролей
- [ ] Система восстановлена с доверенного образа
- [ ] Инцидент и уведомления задокументированы

### 8.8 Отказ Docker/оркестратора

- [ ] Проверен daemon и состояние Compose
- [ ] Перезапуск daemon/compose подтверждён
- [ ] Все сервисы в `healthy`
- [ ] Проверены маршрутизация и LB
- [ ] RTO <= 30 мин, RPO = 0

## 9. Тестирование DR

План тестируется не реже 1 раза в квартал:

- [ ] Восстановление PostgreSQL из последнего backup
- [ ] Симуляция остановки `db` и авто-recovery
- [ ] Симуляция отказа MinIO
- [ ] Тест ротации ключей на тестовой среде
- [ ] Полный restore на чистом хосте

## 10. Контрольные команды

```bash
# 1. Сделать бэкап
./scripts/backup.sh

# 2. Симулировать отказ
docker compose stop db

# 3. Авто-восстановление
python scripts/auto_recovery.py --service db --once

# 4. Проверить восстановление
curl -f http://localhost:8000/health/ready

# 5. Полное восстановление
./scripts/restore.sh /backups/smdg/manifest_latest.txt
```
