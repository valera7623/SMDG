# Инцидент: Медленный DICOM рендеринг

## Симптомы

- p95 рендера > 3s
- таймауты при открытии viewer

## Диагностика

```bash
docker compose logs --since 30m smdg | grep -Ei "dicom|render|timeout|gdcm" | tail -200
curl -s http://localhost:8000/api/bulkhead/status | jq '.dicom'
docker compose exec -T redis redis-cli INFO memory | grep used_memory_human
```

## Восстановление

1. Проверить нагрузку CPU/RAM и I/O.
2. Ограничить параллелизм DICOM запросов.
3. Проверить кэш hit rate Redis (metadata/png).
4. При необходимости временно отключить DICOM viewer.
