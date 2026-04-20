# SMDG Architecture

> **Translation status:** English stub. The authoritative version is
> [`docs/locales/ru/ARCHITECTURE.md`](../locales/ru/ARCHITECTURE.md) and
> will be progressively translated into this file.

## Component overview

```
┌───────────────┐     ┌────────────────┐     ┌───────────────┐
│   Browser /   │────▶│   FastAPI app  │────▶│  PostgreSQL   │
│   API client  │     │   (uvicorn)    │     └───────────────┘
└───────────────┘     │                │     ┌───────────────┐
                      │                │────▶│     Redis     │
                      │                │     └───────────────┘
                      │                │     ┌───────────────┐
                      │                │────▶│ Local FS / S3 │
                      │                │     └───────────────┘
                      │                │     ┌───────────────┐
                      │                │────▶│    ClamAV     │
                      └────────────────┘     └───────────────┘
```

## Runtime layout

- **FastAPI** exposes REST, WebSocket and DICOMweb endpoints.
- **SQLAlchemy 2 async** with **PostgreSQL** is the authoritative store
  (users, tenants, files metadata, webhook deliveries).
- **Redis** powers rate limiting (`slowapi`), metadata caching and
  background task coordination.
- **age** handles symmetric envelope encryption of every file.
- **APScheduler** runs cleanup tasks, webhook retries and key rotations
  when S3 lifecycle policies are not available.

## Request flow (upload)

1. Client sends `POST /api/upload` with a `multipart/form-data` payload.
2. `AuditMiddleware` captures the request.
3. FastAPI route validates size, content type and permissions.
4. File is streamed through ClamAV. A quarantine is applied on
   infection.
5. File is encrypted with `age` and persisted via `StorageBackend`
   (local FS or S3).
6. Metadata is written to PostgreSQL; an audit event is written to
   `audit_logs/`.
7. Response returns the generated file id and download link.

## Security boundaries

- JWT is stored in an HttpOnly, Secure, SameSite=Lax cookie.
- CSRF is mitigated by strict SameSite and double-submit tokens on
  state-changing calls.
- All passwords are hashed with Argon2id.
- Encryption keys live in `keys/` (0600) or an external KMS depending on
  the deployment profile.

Refer to the Russian source document for the full ERD and sequence
diagrams; they will be ported to English in a follow-up translation
pass.
