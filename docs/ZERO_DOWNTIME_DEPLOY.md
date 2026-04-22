# Zero-Downtime Deploy для SMDG

Руководство по обновлению SMDG в production **без простоя для пользователей**.

## Содержание

1. [Принципы](#принципы)
2. [Архитектура](#архитектура)
3. [Быстрый старт](#быстрый-старт)
4. [Сценарии](#сценарии-развёртывания)
5. [Session affinity (Redis)](#session-affinity-через-redis)
6. [Миграции БД](#миграции-бд-без-простоя)
7. [Мониторинг](#мониторинг-деплоя)
8. [Чек-лист перед деплоем](#чек-лист-перед-деплоем)
9. [Troubleshooting](#troubleshooting)

---

## Принципы

**Zero-downtime** = во время обновления приложения никто из пользователей
не получит `502`/`503`/разорванное соединение. Достигается четырьмя
независимыми механизмами, каждый из которых уже присутствует в SMDG:

| Механизм | Где реализовано |
|---|---|
| Readiness probe (`/health/ready` → 503 во время shutdown) | `app/api/health.py` |
| Graceful shutdown (ждём in-flight до 30с, потом SIGKILL) | `app/main.py::lifespan` |
| ≥2 реплики + load balancer с retry | `docker-compose.prod.yml` + `nginx/nginx-zero-downtime.conf` |
| Stateless-контейнеры (файлы → S3, сессии → Redis) | `app/core/storage_backend.py`, `app/core/rate_limiter.py` |

## Архитектура

```
┌────────────────┐      HTTPS       ┌──────────────────┐
│   Пользователь │ ───────────────▶ │     nginx LB     │
└────────────────┘                  │  least_conn      │
                                    │  max_fails=3     │
                                    │  retry 5xx       │
                                    └────────┬─────────┘
                                             │ http://smdg:8000
                            ┌────────────────┼────────────────┐
                            ▼                ▼                ▼
                     ┌───────────┐    ┌───────────┐    ┌───────────┐
                     │ smdg v4.0 │    │ smdg v4.1 │    │ smdg v4.1 │
                     │ (draining)│    │  (ready)  │    │  (ready)  │
                     └─────┬─────┘    └─────┬─────┘    └─────┬─────┘
                           │                │                │
                           └────────┬───────┴────────────────┘
                                    │
                ┌───────────────────┼───────────────────┐
                ▼                   ▼                   ▼
          ┌──────────┐       ┌──────────┐       ┌──────────┐
          │ Postgres │       │  Redis   │       │    S3    │
          │ (single) │       │ sessions │       │  files   │
          └──────────┘       └──────────┘       └──────────┘
```

Ключевой момент — **контейнер stateless**. Любой запрос может быть
обработан любой репликой, потому что:

- Сессии и rate-limit → Redis (`SESSION_REDIS_URL` в `app/main.py`).
- Зашифрованные файлы → S3 (`S3_ENABLED=true` в prod).
- Аудит-логи → общий volume `smdg_audit_logs` + forward в централизованный
  лог-сборщик.

## Быстрый старт

```bash
# 1. Подготовка (один раз)
mkdir -p nginx
cp docker-compose.prod.yml docker-compose.prod.yml.bak   # на всякий
chmod +x scripts/*.sh scripts/*.py

# 2. Обычный prod-деплой: образ уже в Docker Hub
IMAGE_TAG=4.0.1 ./scripts/zero_downtime_deploy.sh

# 3. Локальный тест (образа в registry ещё нет — соберём из Dockerfile)
BUILD_LOCAL=true IMAGE_TAG=dev ./scripts/zero_downtime_deploy.sh

# 4. Тест zero-downtime под нагрузкой
./scripts/test_rolling_update.sh

# 5. Откат (если что)
IMAGE_TAG=4.0.0 ./scripts/zero_downtime_deploy.sh
```

### Режимы сборки образа (`BUILD_LOCAL`)

| Значение | Что делает | Когда использовать |
|---|---|---|
| `auto` (default) | Пытается `docker pull`, при ошибке fallback на `docker build` | Универсальный — работает и локально, и в CI |
| `true` | Всегда `docker build -t ${DOCKER_USERNAME}/smdg:${IMAGE_TAG} .` | Локальное тестирование zero-downtime без Docker Hub |
| `false` | Только `docker pull`, fail-fast при ошибке | Строгий prod: не даём собрать не из CI |

## Сценарии развёртывания

### A. Docker Compose (один сервер) — текущий прод SMDG

```bash
# Запускается через zero_downtime_deploy.sh:
IMAGE_TAG=4.0.1 ./scripts/zero_downtime_deploy.sh

# Внутри скрипта:
#   1. docker compose pull smdg
#   2. docker compose run --rm migrations       ← разовые безопасные миграции
#   3. docker compose up -d --scale smdg=4      ← 2 старых + 2 новых
#   4. curl /health/ready каждой реплики        ← ждём readiness
#   5. docker compose exec nginx nginx -s reload
#   6. docker compose up -d --scale smdg=2      ← останавливаем 2 старых (SIGTERM)
#   7. smoke-test через LB
```

### B. Docker Swarm (несколько нод)

```bash
docker stack deploy -c docker-compose.yml -c docker-compose.prod.yml smdg

# Или обновление одного сервиса:
DEPLOY_TARGET=swarm STACK_NAME=smdg ./scripts/rolling_update.sh 4.0.1
# Что произойдёт:
#   docker service update \
#     --image smdg:4.0.1 \
#     --update-parallelism 1 --update-delay 10s \
#     --update-order start-first \
#     --update-failure-action rollback \
#     smdg_smdg
```

### C. Kubernetes

Рекомендуемый Deployment (сохраните как `k8s/deployment.yaml`):

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: smdg
  namespace: smdg
spec:
  replicas: 3
  revisionHistoryLimit: 5
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1          # +1 новый под
      maxUnavailable: 0    # КРИТИЧНО: 0 = zero-downtime
  selector:
    matchLabels: { app: smdg }
  template:
    metadata:
      labels: { app: smdg }
    spec:
      terminationGracePeriodSeconds: 60
      containers:
        - name: smdg
          image: smdg:4.0.1
          ports: [{ containerPort: 8000 }]
          readinessProbe:
            httpGet: { path: /health/ready, port: 8000 }
            initialDelaySeconds: 10
            periodSeconds: 5
            failureThreshold: 2
            timeoutSeconds: 3
          livenessProbe:
            httpGet: { path: /health/live, port: 8000 }
            periodSeconds: 30
            failureThreshold: 3
          startupProbe:
            httpGet: { path: /health/live, port: 8000 }
            periodSeconds: 5
            failureThreshold: 24
          lifecycle:
            preStop:
              exec:
                command: ["/bin/sh", "-c", "sleep 5"]  # даём endpoints обновиться
```

Деплой:
```bash
DEPLOY_TARGET=k8s K8S_NAMESPACE=smdg ./scripts/rolling_update.sh 4.0.1
```

### D. Portainer / Watchtower (простейший)

В Watchtower достаточно выставить `WATCHTOWER_ROLLING_RESTART=true`
и убедиться, что `deploy.replicas: 2`. Тем не менее, **мы не рекомендуем
Watchtower для prod** — у него нет health-gating на readiness.

## Session affinity через Redis

У SMDG **НЕТ нужды в sticky-сессиях на nginx**, потому что:

1. **JWT** — stateless, токен отдаётся клиенту в cookie `access_token`.
   Любая реплика валидирует подпись через общий `JWT_SECRET_KEY`.
2. **Rate limiter** — уже использует Redis (`slowapi` с `redis://...` storage).
3. **Сессии DICOM Viewer** — токены лежат в Redis.

Убедитесь, что в `.env.prod` прописано:

```dotenv
REDIS_URL=redis://:${REDIS_PASSWORD}@redis:6379/0
JWT_SECRET_KEY_FILE=/run/secrets/jwt_secret_key
S3_ENABLED=true
S3_ENDPOINT_URL=https://s3.eu-central.your-provider.com
```

> **Когда sticky-сессии всё-таки нужны?**
> Только если вы хотите изолировать долгие SSE/WebSocket-соединения
> (ни одно из них не используется в SMDG 4.0). Если в будущем такое
> появится — раскомментируйте `ip_hash;` в `nginx-zero-downtime.conf`
> и уберите `least_conn;`.

### Persistence Redis в prod

В `docker-compose.prod.yml` Redis запускается с:

```yaml
command: >
  redis-server
  --requirepass "${REDIS_PASSWORD}"
  --maxmemory 256mb
  --maxmemory-policy allkeys-lru
  --save 60 1000              # RDB snapshot каждые 60с при 1000+ писках
  --appendonly yes            # AOF: не теряем сессии даже при рестарте Redis
  --appendfsync everysec
```

Это гарантирует, что при рестарте самого Redis (или его ноды в облаке)
сессии пользователей не пропадут.

## Миграции БД без простоя

**Правило номер 1:** новый код N+1 должен работать со схемой версии N.

Алгоритм безопасного ALTER:

| Операция | Опасно | Безопасно |
|---|---|---|
| Добавить колонку | `ADD COLUMN name NOT NULL` | `ADD COLUMN name NULL` → backfill → `SET NOT NULL` следующим релизом |
| Удалить колонку | `DROP COLUMN` в том же релизе, где удалён код | 1) релиз: код не пишет/не читает, 2) релиз: `DROP COLUMN` |
| Переименовать | `RENAME COLUMN` | `ADD new` → dual-write → backfill → `DROP old` |
| Сменить тип | `ALTER COLUMN ... TYPE ...` | `ADD new_typed` → backfill → swap в коде → drop old |
| Новый индекс | `CREATE INDEX` (блокирует) | `CREATE INDEX CONCURRENTLY` (не блокирует) |
| NOT NULL на существующей | `SET NOT NULL` без backfill | backfill → `ALTER COLUMN SET NOT NULL` |

Скрипт `scripts/run_migrations_zero_downtime.py`:

- Берёт **PostgreSQL advisory lock** — одновременно стартующие реплики
  не попытаются мигрировать вместе.
- Выставляет `statement_timeout=30s` и `lock_timeout=5s` — долгий ALTER
  откатится, вместо того чтобы заморозить прод.
- **Pre-flight сканирует** новые миграции regex-ами на опасные паттерны
  (DROP COLUMN, CREATE INDEX без CONCURRENTLY, ALTER COLUMN TYPE).
  Если найден опасный паттерн, но вы уверены — добавьте маркер:

  ```python
  """add new column.

  Revision ID: abc123
  # zero-downtime: allow-unsafe   ← этот маркер разрешает опасные паттерны
  """
  ```

- В `MIGRATION_STRICT_MODE=true` опасные миграции блокируют деплой.

Запуск вручную:

```bash
# Проверить, что будет сделано
python scripts/run_migrations_zero_downtime.py --dry-run

# Применить
python scripts/run_migrations_zero_downtime.py

# До конкретной ревизии (для rollback)
python scripts/run_migrations_zero_downtime.py --revision 43641187ffc2
```

В docker-compose.prod.yml миграции запускаются как отдельный one-shot
сервис `migrations` через `depends_on: condition: service_completed_successfully`.

## Мониторинг деплоя

После подключения `register_deploy_metrics(app)` (уже сделано в
`app/main.py`) в `/metrics` появятся:

```
# Текущая версия и git SHA (labels помогают увидеть mix во время rolling update)
smdg_info{version="4.0.1",git_sha="abc123",replica="smdg-1"} 1
smdg_info{version="4.0.1",git_sha="abc123",replica="smdg-2"} 1

# Готовность каждой реплики (0 во время graceful shutdown)
smdg_ready{replica="smdg-1"} 1
smdg_ready{replica="smdg-2"} 0

# Счётчики попыток деплоя (push-метрики от CI)
smdg_deploy_attempts_total{status="success"} 42
smdg_deploy_attempts_total{status="failed"} 3
smdg_deploy_attempts_total{status="rollback"} 1

# Длительность последнего деплоя
smdg_deploy_duration_seconds{status="success"} 47.2
```

Пример Prometheus alerting правил (`prometheus/rules/deploy.yml`):

```yaml
groups:
  - name: smdg_deploy
    rules:
      - alert: SmdgReplicasNotReady
        expr: sum(smdg_ready) < 2
        for: 1m
        labels: { severity: critical }
        annotations:
          summary: "Меньше 2 реплик SMDG готовы"
          description: "{{ $value }} реплик в состоянии ready"

      - alert: SmdgDeployTookTooLong
        expr: smdg_deploy_duration_seconds{status="success"} > 300
        labels: { severity: warning }

      - alert: SmdgMultipleVersionsLongTerm
        expr: count(count by (version)(smdg_info)) > 1
        for: 10m
        labels: { severity: warning }
        annotations:
          summary: "Rolling update застрял — >1 версии активны 10+ минут"
```

Grafana dashboard (основные панели):

- `sum(rate(http_requests_total[1m])) by (status)` — RPS по кодам.
- `histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket[1m])) by (le))` — p99 latency.
- `sum(smdg_ready)` — текущее число ready-реплик.
- `smdg_deploy_duration_seconds{status="success"}` — последний деплой.

## Чек-лист перед деплоем

Перед первым production-развёртыванием rolling-update:

- [ ] `S3_ENABLED=true` и S3 доступен из всех реплик.
- [ ] `REDIS_PASSWORD` установлен; Redis c `--appendonly yes`.
- [ ] `JWT_SECRET_KEY_FILE` смонтирован секретом в обе реплики.
- [ ] Все volumes, которые монтируются в `smdg`, поддерживают
      одновременный доступ от ≥2 контейнеров (local docker volumes — OK,
      но `./uploads:/app/uploads` bind-mount тоже OK).
- [ ] `alembic upgrade head` применялся как минимум раз для базового состояния.
- [ ] `./scripts/test_rolling_update.sh` проходит на stage.
- [ ] В `prometheus/rules/` добавлены правила из примера выше.
- [ ] TLS-сертификаты валидны и не истекают в ближайшие 30 дней.
- [ ] Есть бэкап БД не старше 24 часов (`docker compose exec backups ls -la`).

## Troubleshooting

**Запросы возвращают `502 Bad Gateway` во время деплоя.**
Вероятно, nginx не перечитал upstream. Проверьте, что reload был успешным:
```
docker compose exec nginx nginx -t && docker compose exec nginx nginx -s reload
```
Убедитесь, что resolver в nginx-конфиге — `127.0.0.11 valid=10s`.

**Readiness не проходит за 90 секунд.**
Проверьте логи реплики:
```
docker compose logs -f --tail=200 smdg
```
Частые причины: медленный старт из-за `init_keys` на больших PEM-файлах,
недоступен Redis/Postgres, не создался bucket S3.

**Миграции висят.**
Запустите:
```
docker compose exec db psql -U smdg_user -d smdg -c \
  "SELECT pid, now()-query_start AS dur, state, query FROM pg_stat_activity \
   WHERE state != 'idle' ORDER BY dur DESC LIMIT 10;"
```
Если на таблице залочился `ALTER` — это повод вернуться к
`run_migrations_zero_downtime.py` и разбить миграцию.

**Все реплики берут трафик, но разная версия кода — некоторые клиенты получают 500.**
Это нормально в течение 10–60 секунд rolling-update; если длительно —
значит readiness-probe отдаёт 200, хотя код несовместим. Добавьте в
миграции новую колонку как nullable, а drop делайте в *следующем* релизе.

**Сессии пользователей слетают при деплое.**
Проверьте, что в обоих репликах один и тот же `JWT_SECRET_KEY` и
`SESSION_REDIS_URL` указывает на общий Redis (не на ephemeral Redis в поде).

---

## Связанные файлы

- `docker-compose.prod.yml` — deploy/update_config на 2 реплики.
- `nginx/nginx-zero-downtime.conf` — upstream с DNS resolver и retry.
- `scripts/zero_downtime_deploy.sh` — автоматический pipeline деплоя.
- `scripts/rolling_update.sh` — обёртка для compose / swarm / k8s.
- `scripts/run_migrations_zero_downtime.py` — безопасные миграции.
- `scripts/test_rolling_update.sh` — автоматический smoke-тест.
- `.github/workflows/deploy-rolling.yml` — CI/CD.
- `app/api/deploy_metrics.py` — Prometheus-метрики.
