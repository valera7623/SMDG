# Working with files

Upload, view and delete medical files in SMDG.

## Upload

1. Open the **Files** section.
2. Click **Upload** or drag a file into the drop zone.
3. Wait for completion — the file is encrypted on the server (age).

### Limits

| Parameter | Default |
|-----------|---------|
| Max size | `MAX_UPLOAD_SIZE_MB` (600 MB in `.env.example`) |
| Allowed types | MIME and extension validation |
| `demo` profile | Reduced upload cap |

!!! warning "Encryption"
    Files are encrypted **before** being written to disk or S3. Decryption happens only for authorised downloads or one-shot links.

## File list

The table shows:

- file name;
- size;
- upload date;
- owner;
- actions (download, create link, delete, DICOM).

Filtering and sorting are available in column headers.

## Download

1. Click **Download** on the desired file.
2. The browser receives the decrypted file (`application/octet-stream`).

Downloads are recorded in the audit log (`file.downloaded`).

## Delete

Only the owner or `admin` can delete a file:

1. Click **Delete**.
2. Confirm the action.

Ciphertext is removed from storage and the DB row is deleted. A `file.deleted` webhook event is sent if configured.

## Storage

Depending on the deployment profile:

| Profile | Storage |
|---------|---------|
| `russia`, `single`, `demo` | Local disk |
| `intl`, `saas` | S3 / MinIO |

See [Configuration](../admin-guide/configuration.md).

## API

Programmatic upload: `POST /api/upload` (multipart/form-data).

See [API — files](../api/files.md).
