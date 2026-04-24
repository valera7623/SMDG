# SMDG DICOM Runbook

## Назначение

DICOM endpoints отвечают за выдачу view token, DICOMweb (QIDO/WADO), рендер PNG и metadata.

## Проверки

```bash
curl -s http://localhost:8000/health | jq '.features.dicom_viewer'
curl -s http://localhost:8000/api/bulkhead/status | jq '.dicom'
docker compose logs --since 30m smdg | grep -i dicom | tail -50
```

## Диагностика проблем

- Медленный рендер -> см. `incidents/dicom-slow.md`
- Ошибки декомпрессии -> проверить pydicom/gdcm зависимости
- 401 по токену -> проверить TTL view token и синхронизацию времени

## Временные меры

- Снизить параллелизм DICOM через bulkhead/конфиг
- При критической деградации временно отключить DICOM viewer
