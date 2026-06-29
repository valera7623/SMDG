# API — files

## Upload

```http
POST /api/upload
Content-Type: multipart/form-data
Cookie: access_token=<JWT>

file=@report.pdf
```

Response (example):

```json
{
  "id": "uuid",
  "filename": "report.pdf",
  "size": 102400,
  "uploaded_at": "2026-06-29T12:00:00Z"
}
```

Webhook event: `file.uploaded`.

## List files

```http
GET /api/files
Cookie: access_token=<JWT>
```

## Download

```http
GET /api/download/{file_id}
Cookie: access_token=<JWT>
```

Response: `application/octet-stream`.

## Delete

```http
DELETE /api/files/{file_id}
Cookie: access_token=<JWT>
```

Webhook event: `file.deleted`.

## Limits

- `MAX_UPLOAD_SIZE_MB` — maximum size.
- MIME and extension validated before encryption.
- Rate limiting: see [API overview](index.md).

## Encryption

Files are encrypted with **age** before storage. Clients receive decrypted bytes only on authorised download.
