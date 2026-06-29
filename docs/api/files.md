# API — файлы

## Загрузка

```http
POST /api/upload
Content-Type: multipart/form-data
Cookie: access_token=<JWT>

file=@report.pdf
```

Ответ (пример):

```json
{
  "id": "uuid",
  "filename": "report.pdf",
  "size": 102400,
  "uploaded_at": "2026-06-29T12:00:00Z"
}
```

Событие webhook: `file.uploaded`.

## Список файлов

```http
GET /api/files
Cookie: access_token=<JWT>
```

## Скачивание

```http
GET /api/download/{file_id}
Cookie: access_token=<JWT>
```

Ответ: `application/octet-stream`.

## Удаление

```http
DELETE /api/files/{file_id}
Cookie: access_token=<JWT>
```

Событие webhook: `file.deleted`.

## Ограничения

- `MAX_UPLOAD_SIZE_MB` — максимальный размер.
- MIME и расширение проверяются до шифрования.
- Rate limiting: см. [обзор API](index.md).

## Шифрование

Файл шифруется **age** перед записью. Клиент получает расшифрованные байты только при авторизованном скачивании.
