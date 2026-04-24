# SMDG Redis Runbook

## Назначение

Redis используется для rate limiting, кэшей (включая DICOM metadata/PNG), служебных счетчиков.

## Проверки

```bash
docker compose exec -T redis redis-cli PING
docker compose exec -T redis redis-cli INFO memory | grep used_memory_human
docker compose exec -T redis redis-cli INFO stats | grep evicted_keys
```

## Типовые симптомы

- Рост `evicted_keys` -> не хватает памяти
- Частые timeouts -> сеть/CPU pressure
- Rate limit anomalies -> проверить Redis доступность и keyspace

## Действия

```bash
docker compose restart redis
docker compose logs --tail=200 redis
```

Для прод-среды избегать `FLUSHALL` без согласования.
