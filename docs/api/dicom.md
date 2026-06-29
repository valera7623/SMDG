# API — DICOM

## View URL (авторизованный доступ)

```http
POST /api/dicom/view-url
Content-Type: application/json
Cookie: access_token=<JWT>

{"file_id": "uuid"}
```

Ответ:

```json
{
  "view_url": "/dicom-viewer?...",
  "token": "short-lived-view-token",
  "study_uid": "1.2.3..."
}
```

## Метаданные

```http
GET /api/dicom/metadata/{file_id}?token=<view_token>
```

## Рендер PNG

```http
GET /api/dicom/render/{file_id}?token=<view_token>&frame=0
```

Ответ: `image/png`.

## DICOMweb

### QIDO-RS

```http
GET /qido-rs/studies
GET /qido-rs/studies/{studyUID}/series
```

### WADO-RS

```http
GET /wado-rs/studies/{studyUID}/series/{seriesUID}/instances/{instanceUID}
```

## Кэш

Метаданные и PNG кэшируются в Redis (`smdg:dicom_meta:{file_id}`, TTL ~2.25 ч).

## Аудит

| Событие | Описание |
|---------|----------|
| `dicom.view_initiated` | Открыт viewer |
| `dicom.metadata_accessed` | Запрос метаданных |
| `dicom.streamed` | Отдан PNG-кадр |

Подробнее: [user-guide/dicom.md](../user-guide/dicom.md).
