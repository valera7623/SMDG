**English** | [Русский](README.ru.md) | [Deutsch](README.de.md) | [Français](README.fr.md)

# SMDG — Secure Medical Data Gateway

**Self-hosted, end-to-end encrypted medical file exchange.**

Version: **4.0.0** (core and DICOM Viewer) · audit export: **3.1.0**.

SMDG lets doctors, clinics and patients exchange medical files safely.
Every file is encrypted server-side with [age](https://age-encryption.org/),
protected by time-limited one-shot links, scanned by ClamAV and logged in
a full audit trail. A built-in DICOM viewer renders studies in the browser
without shipping decrypted data to the client.

## Documentation

Full user- and operator-facing documentation lives in
[`docs/`](docs/README.md). The English source of truth sits under
[`docs/src/`](docs/src/), with translations under
[`docs/locales/{ru,de,fr}/`](docs/locales/).

- Overview — [`docs/src/README.md`](docs/src/README.md)
- API guide — [`docs/src/API_GUIDE.md`](docs/src/API_GUIDE.md)
- Architecture — [`docs/src/ARCHITECTURE.md`](docs/src/ARCHITECTURE.md)
- Deployment profiles — [`docs/src/DEPLOYMENT.md`](docs/src/DEPLOYMENT.md)
- DICOM Viewer — [`docs/src/DICOM_VIEWER.md`](docs/src/DICOM_VIEWER.md)
- Security policy — [`docs/src/SECURITY.md`](docs/src/SECURITY.md)

## Quick start

```bash
git clone <your-repo>
cd smdg
cp .env.example .env
docker compose up --build
```

Open <https://localhost>. Default dev credentials: `admin` / `admin`
(change them immediately).

## Deployment profiles

The environment variable `DEPLOYMENT_TYPE` selects the feature matrix:

| Profile  | Summary                                                         |
|----------|-----------------------------------------------------------------|
| `russia` | FZ-152 compliant: local storage, mandatory 2FA, 3-year audit    |
| `intl`   | S3/MinIO, DICOM, GDPR/HIPAA-oriented features                   |
| `single` | Single tenant, simplified admin, local disk by default          |
| `saas`   | Multi-tenant, billing/white-label, object storage               |

See [`docs/src/DEPLOYMENT.md`](docs/src/DEPLOYMENT.md) for details.

## Multilingual support

- Web UI: English / Русский / Deutsch / Français with a runtime language
  switcher (see [`static/js/i18n.js`](static/js/i18n.js)).
- API documentation: `/docs` (English), `/docs/ru`, `/docs/de`, `/docs/fr`
  and `/openapi.{ru,de,fr}.json`.
- User documentation: `docs/src/` (English) + `docs/locales/<lang>/`.

## License

MIT. Author: Valeriy Popov.
