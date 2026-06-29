# API — DICOM

## View URL (authenticated)

```http
POST /api/dicom/view-url
Content-Type: application/json
Cookie: access_token=<JWT>

{"file_id": "uuid"}
```

Response:

```json
{
  "view_url": "/dicom-viewer?...",
  "token": "short-lived-view-token",
  "study_uid": "1.2.3..."
}
```

## Metadata

```http
GET /api/dicom/metadata/{file_id}?token=<view_token>
```

## PNG render

```http
GET /api/dicom/render/{file_id}?token=<view_token>&frame=0
```

Response: `image/png`.

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

## Cache

Metadata and PNG frames are cached in Redis (`smdg:dicom_meta:{file_id}`, TTL ~2.25 h).

## Audit

| Event | Description |
|-------|-------------|
| `dicom.view_initiated` | Viewer opened |
| `dicom.metadata_accessed` | Metadata requested |
| `dicom.streamed` | PNG frame served |

See [user-guide/dicom.md](../user-guide/dicom.md).
