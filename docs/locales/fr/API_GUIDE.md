<!-- smdg-i18n-header-start
source: docs/src/API_GUIDE.md
source_sha1: ca3dfa26670673cb4087f0facd55128535dfaf8f
language: fr
last_sync: 2026-05-31
status: translated
smdg-i18n-header-end -->

# Guide de l'API SMDG

> **Statut de traduction :** cette page est la traduction française du guide
> de l'API SMDG. La version russe faisant autorité se trouve dans
> [`docs/locales/ru/API_GUIDE.md`](../ru/API_GUIDE.md) et contient des
> exemples complets.

## Aperçu

L'API SMDG est une API REST conforme à OpenAPI 3 / Swagger, servie par
FastAPI. La documentation interactive est disponible à :

- `/docs` — Swagger UI (anglais, source de vérité)
- `/openapi.json` — schéma OpenAPI (anglais)
- `/openapi.ru.json` — schéma OpenAPI avec descriptions en russe
- `/openapi.de.json` — schéma OpenAPI avec descriptions en allemand
- `/openapi.fr.json` — schéma OpenAPI avec descriptions en français
- `/redoc` — ReDoc UI

## Authentification

SMDG utilise des jetons d'accès JWT stockés dans un cookie HttpOnly
`access_token`. Tous les points de terminaison en écriture nécessitent une
authentification. Le contrôle d'accès basé sur les rôles distingue `admin`,
`doctor`, `user` et `super_admin`.

## Principaux points de terminaison

| Domaine         | Point de terminaison              | Méthode      |
|-----------------|-----------------------------------|--------------|
| Authentification | `/api/auth/login`                | POST         |
| Authentification | `/api/auth/logout`               | POST         |
| Authentification | `/api/auth/register`             | POST         |
| Authentification | `/api/auth/change-password`      | POST         |
| Authentification | `/api/auth/setup-2fa`            | POST         |
| Authentification | `/api/auth/verify-2fa-setup`     | POST         |
| Authentification | `/api/auth/disable-2fa`          | POST         |
| Fichiers        | `/api/upload`                     | POST         |
| Fichiers        | `/api/files`                      | GET          |
| Fichiers        | `/api/download/{file_id}`         | GET          |
| Fichiers        | `/api/files/{file_id}`            | DELETE       |
| Admin utilisateurs | `/api/admin/users`             | GET/POST     |
| Admin utilisateurs | `/api/admin/users/{id}`        | DELETE       |
| Export d'audit  | `/api/admin/audit/export`         | GET          |
| Audit fichiers  | `/api/admin/file-audit/`          | GET          |
| DICOM           | `/api/dicom/studies`              | GET          |
| DICOMweb        | `/wado-rs/...`, `/qido-rs/...`    | GET          |
| Webhooks        | `/api/webhooks`                   | GET/POST     |
| Health          | `/health`, `/health/live`, `/health/ready` | GET |
| Feature flags   | `/health/features`, `/health/deployment` | GET   |
| SLO / SLI       | `/api/slo`, `/api/sli`            | GET          |
| Démo (mode démo)| `/api/demo/info`                  | GET          |
| Métriques       | `/metrics`                        | GET          |

## API d'export d'audit

`GET /api/admin/audit/export?format=xlsx|pdf|csv&from=YYYY-MM-DD&to=YYYY-MM-DD`

- Nécessite le rôle `admin`.
- `format` — l'un de `xlsx`, `pdf`, `csv`.
- `from` / `to` — plage de dates inclusive (UTC).
- Filtres facultatifs : `user_id`, `action`, `resource_type`.
- Réponse : `application/octet-stream` avec un en-tête de pièce jointe
  `Content-Disposition`.

## Modèle d'erreur

Toutes les erreurs renvoient une charge utile JSON :

```json
{
  "detail": "message anglais lisible par machine",
  "code": "code_erreur_optionnel"
}
```

Les clients sont responsables de présenter des versions localisées des
messages d'erreur. Le serveur émet toujours des chaînes en anglais.

## Limitation de débit

Les limites sont appliquées par IP via slowapi (basées sur Redis en mode mis à
l'échelle) et sont configurables via des variables d'environnement (voir
`.env.example`).

| Portée                      | Par défaut                 | Variable d'environnement |
|-----------------------------|----------------------------|--------------------------|
| Valeur globale par défaut   | `100/minute`               | `RATE_LIMIT_DEFAULT`     |
| Connexion (`/api/auth/login`) | `10/minute;5/10seconds`  | `RATE_LIMIT_LOGIN`       |
| Inscription (`/api/auth/register`) | `10/minute` (`3/hour` en démo) | `RATE_LIMIT_REGISTER` |
| `change-password`, `verify-2fa-setup` | `5/minute`      | —                        |
| `setup-2fa`, `disable-2fa`  | `3/minute`                 | —                        |
| `logout`                    | `60/minute`                | —                        |

Les réponses `429 Too Many Requests` incluent un en-tête `Retry-After`.
