<!-- smdg-i18n-header-start
source: docs/src/API_GUIDE.md
source_sha1: ca3dfa26670673cb4087f0facd55128535dfaf8f
language: de
last_sync: 2026-05-31
status: translated
smdg-i18n-header-end -->

# SMDG API-Leitfaden

> **Übersetzungsstatus:** Diese Seite ist die deutsche Übersetzung des SMDG
> API-Leitfadens. Die maßgebliche russische Version befindet sich unter
> [`docs/locales/ru/API_GUIDE.md`](../ru/API_GUIDE.md) und enthält
> ausführliche Beispiele.

## Überblick

Die SMDG-API ist eine OpenAPI-3- / Swagger-konforme REST-API, die von
FastAPI bereitgestellt wird. Interaktive Dokumentation ist verfügbar unter:

- `/docs` — Swagger UI (Englisch, Quelle der Wahrheit)
- `/openapi.json` — OpenAPI-Schema (Englisch)
- `/openapi.ru.json` — OpenAPI-Schema mit russischen Beschreibungen
- `/openapi.de.json` — OpenAPI-Schema mit deutschen Beschreibungen
- `/openapi.fr.json` — OpenAPI-Schema mit französischen Beschreibungen
- `/redoc` — ReDoc UI

## Authentifizierung

SMDG verwendet JWT-Zugriffstokens, die in einem HttpOnly-Cookie
`access_token` gespeichert werden. Alle schreibenden Endpunkte erfordern
eine Authentifizierung. Die rollenbasierte Zugriffskontrolle unterscheidet
`admin`, `doctor`, `user` und `super_admin`.

## Wichtigste Endpunkte

| Bereich         | Endpunkt                          | Methode      |
|-----------------|-----------------------------------|--------------|
| Authentifizierung | `/api/auth/login`               | POST         |
| Authentifizierung | `/api/auth/logout`              | POST         |
| Authentifizierung | `/api/auth/register`            | POST         |
| Authentifizierung | `/api/auth/change-password`     | POST         |
| Authentifizierung | `/api/auth/setup-2fa`           | POST         |
| Authentifizierung | `/api/auth/verify-2fa-setup`    | POST         |
| Authentifizierung | `/api/auth/disable-2fa`         | POST         |
| Dateien         | `/api/upload`                     | POST         |
| Dateien         | `/api/files`                      | GET          |
| Dateien         | `/api/download/{file_id}`         | GET          |
| Dateien         | `/api/files/{file_id}`            | DELETE       |
| Admin-Benutzer  | `/api/admin/users`                | GET/POST     |
| Admin-Benutzer  | `/api/admin/users/{id}`           | DELETE       |
| Audit-Export    | `/api/admin/audit/export`         | GET          |
| Datei-Audit     | `/api/admin/file-audit/`          | GET          |
| DICOM           | `/api/dicom/studies`              | GET          |
| DICOMweb        | `/wado-rs/...`, `/qido-rs/...`    | GET          |
| Webhooks        | `/api/webhooks`                   | GET/POST     |
| Health          | `/health`, `/health/live`, `/health/ready` | GET |
| Feature-Flags   | `/health/features`, `/health/deployment` | GET   |
| SLO / SLI       | `/api/slo`, `/api/sli`            | GET          |
| Demo (Demo-Modus)| `/api/demo/info`                 | GET          |
| Metriken        | `/metrics`                        | GET          |

## Audit-Export-API

`GET /api/admin/audit/export?format=xlsx|pdf|csv&from=YYYY-MM-DD&to=YYYY-MM-DD`

- Erfordert die Rolle `admin`.
- `format` — eines von `xlsx`, `pdf`, `csv`.
- `from` / `to` — einschließlicher Datumsbereich (UTC).
- Optionale Filter: `user_id`, `action`, `resource_type`.
- Antwort: `application/octet-stream` mit einem
  `Content-Disposition`-Anhang-Header.

## Fehlermodell

Alle Fehler liefern eine JSON-Nutzlast:

```json
{
  "detail": "maschinenlesbare englische Meldung",
  "code": "optionaler_fehlercode"
}
```

Die Clients sind dafür verantwortlich, lokalisierte Versionen der
Fehlermeldungen anzuzeigen. Der Server gibt stets englische Zeichenketten aus.

## Ratenbegrenzung

Die Limits werden pro IP über slowapi durchgesetzt (im skalierten Modus
Redis-gestützt) und sind über Umgebungsvariablen konfigurierbar (siehe
`.env.example`).

| Bereich                     | Standard                   | Env-Override            |
|-----------------------------|----------------------------|-------------------------|
| Globaler Standard           | `100/minute`               | `RATE_LIMIT_DEFAULT`    |
| Login (`/api/auth/login`)   | `10/minute;5/10seconds`    | `RATE_LIMIT_LOGIN`      |
| Registrierung (`/api/auth/register`) | `10/minute` (`3/hour` im Demo) | `RATE_LIMIT_REGISTER` |
| `change-password`, `verify-2fa-setup` | `5/minute`      | —                       |
| `setup-2fa`, `disable-2fa`  | `3/minute`                 | —                       |
| `logout`                    | `60/minute`                | —                       |

Antworten mit `429 Too Many Requests` enthalten einen `Retry-After`-Header.
