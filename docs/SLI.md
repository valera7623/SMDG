# Service Level Indicators (SLI) — SMDG

Документ связывает **бизнес-SLA** (см. [SLA.md](./SLA.md)) с **измеряемыми** показателями в Prometheus / приложении. Имена метрик соответствуют экспорту SMDG (`/metrics`) и `prometheus/`-конфигурации.

## 1. Базовые PromQL-запросы

> Подставьте к селекторам `job`/`instance` в соответствии со своим `scrape` (у нас часто `job="smdg"`). Для агрегации реплик используйте `sum without (instance) (...)`).

### 1.1. Доступность API (доля 2xx)

```promql
# SLI: доля успешных HTTP-запросов (2xx) за 5m
100 * sum(rate(http_requests_total{status=~"2.."}[5m]))
  / sum(rate(http_requests_total[5m]))
```

**Пороги (ориентиры для алертов):**

| Статус | Условие |
|--------|---------|
| Цель (SLO) | ≥ 99,9% (по 30d rolling — см. recording rules) |
| Предупреждение | &lt; 99,5% (короткое окно) |
| Критично | &lt; 99,0% |

### 1.2. Латентность API (p95 / p99)

```promql
# p95 (стандартный histogram от Instrumentator)
histogram_quantile(0.95,
  sum(rate(http_request_duration_seconds_bucket[5m])) by (le)
)

# p99
histogram_quantile(0.99,
  sum(rate(http_request_duration_seconds_bucket[5m])) by (le)
)
```

**Пороги (секунды):**

| | p95 | p99 |
|---|-----|-----|
| Цель | &lt; 0,5 | &lt; 1,0 |
| Предупреждение | &gt; 1 | &gt; 2 |
| Критично | &gt; 2 | &gt; 5 |

> Дублирование: гaugи `smdg_api_latency_p50` / `p90` / `p99` обновляются `app/core/slo_collector.py` — удобны для single-stat без PromQL.

### 1.3. DICOM: успешность рендеров (прокси-SLI)

Счётчики: `dicom_render_failures_total`, `dicom_render_duration_seconds_count` (histogram `…_count` = число рендеров).

```promql
# Оценка: 1 - (ошибки / все попытки)
1 - (
  sum(rate(dicom_render_failures_total[5m]))
  / clamp_min(sum(rate(dicom_render_duration_seconds_count[5m])), 1e-9)
)
```

**Пороги:** цель 99,9% «успешных» относительно этой модели; при нулевом трафике осторожно интерпретировать (график = «нет данных»).

### 1.4. Внутренние gauge’ы (без `rate()`)

Экспортируются из приложения (обновляются раз в минуту, см. SLO collector):

- `smdg_api_availability` — %
- `smdg_db_availability` / `smdg_redis_availability` / `smdg_storage_availability`
- `smdg_slo_compliance{slo_name, target}` — compliance по под-SLO
- `smdg_error_budget_remaining_seconds{slo_name}`

Запрос «потребление error budget в долях» для API:

```promql
smdg_error_budget_spent_seconds{slo_name="api_availability"}
/ clamp_min(
    (1 - 0.999) * 30 * 24 * 3600,
    1
)
```

(Точный знаменатель согласуется с `SLO_CONFIG` в `slo_collector`.)

## 2. Записываемые ряды (recording rules)

См. `prometheus/sla-rules.yml` (префикс `smdg:`). После перезагрузки конфига:

```bash
curl -X POST http://localhost:9090/-/reload
```

Проверка:

```bash
curl -s 'http://localhost:9090/api/v1/query?query=smdg:api_availability:30d' | jq .
```

## 3. Графановская панель (JSON, концепт)

Ниже — **схема** дашборда (импортируйте вручную или через provisioning). Используйте datasource Prometheus.

```json
{
  "title": "SLA / SLO — SMDG",
  "timezone": "browser",
  "panels": [
    {
      "type": "stat",
      "title": "API availability (30d, recorded)",
      "targets": [{ "expr": "smdg:api_availability:30d" }],
      "fieldConfig": {
        "defaults": {
          "thresholds": {
            "steps": [
              { "color": "red", "value": 0 },
              { "color": "yellow", "value": 99.5 },
              { "color": "green", "value": 99.9 }
            ]
          },
          "unit": "percent"
        }
      }
    },
    {
      "type": "gauge",
      "title": "Error budget (proxy, API)",
      "targets": [{ "expr": "smdg:error_budget_consumed:ratio" }]
    },
    {
      "type": "graph",
      "title": "Burn: 1h bad ratio vs 0.1% SLO",
      "targets": [{ "expr": "smdg:bad_ratio:1h" }]
    }
  ]
}
```

## 4. Инструменты в репозитории

| Что | Где |
|-----|-----|
| SLI/отчёты из приложения (без внешнего Prom) | `app/core/sla_tracker.py` |
| CLI-обёртка | `scripts/sla_tracker.py` |
| Публичный JSON статуса | `GET /api/sli/status` |
| Месячный отчёт (HTML) | `scripts/monthly_sla_report.py` |
| Существующий SLO API | `GET /api/slo/report` (admin) |

## 5. Согласованность с алертами

Правила в `prometheus/sla-rules.yml` **дополняют** `prometheus/alerts.yml` (не дублируют `SMDGApiDown` и т.д.; имена алертов `SMDGSLA*`).

## 6. Устранение неполадок

| Симптом | Возможная причина |
|--------|-------------------|
| `GET /api/sli` → **404** | Не перезапущен процесс после обновления кода; образ Docker не пересобран. Проверьте `GET /api/sli` и `GET /api/sli/status`. |
| PromQL `smdg:api_availability:30d` **пустой** | В `prometheus.yml` не подключён `sla-rules.yml` или не выполнен `POST /-/reload`; нет данных `http_requests_total` за 30d (свежий Prom); другой `job` — поправьте селектор. |
| Скрипт / отчёт: **0%** и `error` | Не запущен SMDG (нет счётчика SLO) или ноль запросов — это ожидаемо. После ответа `200` с реального API `insufficient_data` в JSON будет `true`, статус `unknown`. |

---

**Версия:** 1.0 · **Дата:** 2026-04-25
