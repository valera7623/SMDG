# Частые проблемы

## API недоступен

```bash
docker compose ps smdg nginx
docker compose logs --tail=200 smdg nginx
curl -v http://localhost:8000/health
```

## БД недоступна

```bash
docker compose ps db
docker compose exec -T db pg_isready -U smdg_user
```

## Redis недоступен

```bash
docker compose ps redis
docker compose exec -T redis redis-cli PING
```

## Минутный triage чеклист

1. Контейнеры живы?
2. Health endpoints отвечают?
3. Есть массовые ошибки в логах?
4. Диск/память/CPU в норме?
5. Сработали circuit breaker/bulkhead?
