# Инцидент: Высокая нагрузка CPU

## Симптомы

- CPU > 80% более 10 минут
- рост latency и 504

## Диагностика

```bash
docker stats smdg-smdg-1 --no-stream
top -bn1 | head -20
docker compose exec -T smdg top -bn1
docker compose logs --tail=1000 smdg | grep -Ei "dicom|render|upload"
curl -s http://localhost:8000/api/bulkhead/status | jq '.dicom'
```

## Восстановление

1. Ограничить источник нагрузки (rate limit / bulkhead).
2. При необходимости масштабировать `smdg` (`--scale smdg=3`).
3. Временное отключение DICOM при P1 деградации.
4. После стабилизации запустить RCA.
