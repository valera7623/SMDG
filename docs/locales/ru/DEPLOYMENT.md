<!-- smdg-i18n-header-start
source: docs/src/DEPLOYMENT.md
source_sha1: 836132a041338d707275005b013252066a179eb1
language: ru
last_sync: 2026-05-31
status: needs-translation
smdg-i18n-header-end -->

# Типы развёртывания SMDG

Переменная окружения **`DEPLOYMENT_TYPE`**: `russia` | `intl` | `single` | `saas`.

## Russia (`russia`)

- Локальное хранилище (`S3_ENABLED=false`).
- Обязательная 2FA на уровне политики входа.
- Аудит 1095 дней (`AUDIT_3_YEARS` в матрице).
- Криптопрофиль ГОСТ (`GOST_CRYPTO`): сейчас заглушка поверх age — замените перед продакшеном.

```bash
docker build --build-arg DEPLOYMENT_TYPE=russia -t smdg:russia .
docker compose -f docker-compose.yml -f docker-compose.russia.yml up -d
```

## International (`intl`)

- S3 / MinIO, DICOM Viewer, GDPR-ориентированные фичи в матрице.

```bash
DEPLOYMENT_TYPE=intl docker compose up -d
```

Используйте overlay `docker-compose.intl.yml` для лимитов ресурсов.

## Single tenant (`single`)

- Один tenant по умолчанию, упрощённая админка (`SIMPLE_ADMIN`), локальное хранилище по умолчанию.
- При выключенном `MULTI_TENANCY` роль **`super_admin`** не переключает организацию через `Host` или `X-Tenant-*`: контекст всегда tenant с `tenant_default_subdomain` (как у остальных ролей). Это исключает скрытый multi-tenant в single-профиле.

```bash
docker compose -f docker-compose.yml -f docker-compose.single.yml up -d
```

Если в `.env` уже включён S3 с валидными ключами, приложение сохранит совместимость и продолжит использовать S3.

## SaaS (`saas`)

- Multi-tenancy, биллинг и white-label в матрице; требуется рабочий S3 вне dev.

```bash
docker compose -f docker-compose.yml -f docker-compose.saas.yml up -d
```

## Горизонтальное масштабирование (stateless-кластер)

Используйте `docker-compose.scale.yml`, когда нужны несколько реплик приложения
за Nginx-балансировщиком.

### Требования к архитектуре

- Узлы приложения должны оставаться stateless.
- Сессии, кэш и очередь задач храните в Redis:
  - `HORIZONTAL_SCALING_REDIS_SESSION_URL`
  - `HORIZONTAL_SCALING_REDIS_CACHE_URL`
  - `HORIZONTAL_SCALING_REDIS_JOB_QUEUE_URL`
- Для файлов используйте общее объектное хранилище (`S3`/`MinIO`).
- Весь входящий трафик направляйте через `nginx-lb`
  (`nginx/nginx-load-balancer.conf`).

### Запуск и масштабирование

```bash
# Базовый запуск кластера (порты: 18080 HTTP, 18443 HTTPS)
docker compose -p smdg-scale -f docker-compose.scale.yml up -d

# Масштабирование до 3 реплик приложения
docker compose -p smdg-scale -f docker-compose.scale.yml up -d --scale smdg=3

# Или через helper-скрипт
./scripts/scale.sh 3
```

### Проверка readiness и балансировки

```bash
# Ready-статус через балансировщик
curl -k https://localhost:18443/health/ready

# Проверка распределения запросов между репликами
for i in {1..30}; do
  curl -ks https://localhost:18443/health/ready | jq -r '.instance_id'
done | sort | uniq -c
```

Используйте `/health/live` для liveness probe, `/health/ready` для маршрутизации
оркестратором, `/health/metrics` для per-instance метрик.

### Blue/green cutover

**Масштабируемый кластер** (`smdg-scale`, `docker-compose.scale.yml`): скрипт
`./scripts/cutover.sh` копирует фрагменты upstream из `nginx/upstreams/` в
`nginx/nginx-load-balancer.conf`, проверяет конфиг и перезагружает
`nginx-lb`. Режимы: `status`, `blue` (все реплики), `green <n>` (только
реплика *n*), `canary`, `rollback`.

```bash
./scripts/cutover.sh status
./scripts/cutover.sh blue
./scripts/cutover.sh green 2
```

`./scripts/deploy.sh` пересобирает сервис приложения и при успешной
проверке здоровья вызывает `./scripts/cutover.sh green <инстанс>`.

**Схема с include** (с `include ... upstream-target.conf` и
`proxy_pass $smdg_upstream;`):

```bash
./scripts/cutover_include.sh blue
./scripts/cutover_include.sh green
```

**Edge-контейнер** (замена upstream в одном Nginx, без scale compose):

```bash
EDGE_NGINX_CONTAINER=smdg-nginx-1 ./scripts/cutover_edge.sh
```

Include- и edge-скрипты проверяют Nginx, делают post-cutover health-check и
auto-rollback (переменные — в шапке скриптов).

Отдельный runbook по откату:
[`docs/runbooks/rollback-to-baseline.md`](../../runbooks/rollback-to-baseline.md).

## Миграция со старой версии

1. Задайте `DEPLOYMENT_TYPE` (для текущего docker-стека с MinIO рекомендуется `intl`).
2. Запустите `python scripts/migrate_deployment_type.py --target <тип>` для чеклиста.
3. Перезапустите сервисы.

Шаблоны `.env`: `.env.<profile>.example` в корне репозитория.

## Runbooks для эксплуатации

Для production-операций и инцидентов используйте:

- Главный индекс: [`docs/runbooks/README.md`](../../runbooks/README.md)

Ежедневные/регулярные операции:

- Daily checks: [`docs/runbooks/operations/daily-checks.md`](../../runbooks/operations/daily-checks.md)
- Weekly maintenance: [`docs/runbooks/operations/weekly-maintenance.md`](../../runbooks/operations/weekly-maintenance.md)
- Monthly tasks: [`docs/runbooks/operations/monthly-tasks.md`](../../runbooks/operations/monthly-tasks.md)
- Backup and recovery: [`docs/runbooks/operations/backup-recovery.md`](../../runbooks/operations/backup-recovery.md)

Компонентные playbooks:

- API: [`docs/runbooks/components/smdg-api.md`](../../runbooks/components/smdg-api.md)
- PostgreSQL: [`docs/runbooks/components/smdg-database.md`](../../runbooks/components/smdg-database.md)
- Redis: [`docs/runbooks/components/smdg-redis.md`](../../runbooks/components/smdg-redis.md)
- Storage: [`docs/runbooks/components/smdg-storage.md`](../../runbooks/components/smdg-storage.md)
- DICOM: [`docs/runbooks/components/smdg-dicom.md`](../../runbooks/components/smdg-dicom.md)
- Auth: [`docs/runbooks/components/smdg-auth.md`](../../runbooks/components/smdg-auth.md)
- Audit: [`docs/runbooks/components/smdg-audit.md`](../../runbooks/components/smdg-audit.md)
- Webhooks: [`docs/runbooks/components/smdg-webhooks.md`](../../runbooks/components/smdg-webhooks.md)

Ключевые инциденты:

- High CPU: [`docs/runbooks/incidents/high-cpu.md`](../../runbooks/incidents/high-cpu.md)
- High memory: [`docs/runbooks/incidents/high-memory.md`](../../runbooks/incidents/high-memory.md)
- DB connection limit: [`docs/runbooks/incidents/db-connection-limit.md`](../../runbooks/incidents/db-connection-limit.md)
- Disk full: [`docs/runbooks/incidents/disk-full.md`](../../runbooks/incidents/disk-full.md)
