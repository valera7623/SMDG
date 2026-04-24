# Инцидент: Высокое потребление памяти

## Симптомы

- Memory > 85%
- OOMKill контейнеров

## Диагностика

```bash
docker stats --no-stream
free -m
docker compose logs --tail=300 smdg | grep -Ei "oom|memory|killed"
docker compose exec -T redis redis-cli INFO memory | grep used_memory_human
```

## Восстановление

1. Перезапустить проблемный контейнер.
2. Снизить нагрузку (ограничить тяжелые запросы).
3. Проверить утечки: длинные запросы, большие payload, кэш.
4. Временно увеличить лимиты памяти или scale-out.
