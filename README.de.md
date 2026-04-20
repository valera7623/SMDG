[English](README.md) | [Русский](README.ru.md) | **Deutsch** | [Français](README.fr.md)

# SMDG — Secure Medical Data Gateway

**Selbstgehostetes Gateway für medizinische Dateien mit Ende-zu-Ende-Verschlüsselung.**

Version: **4.0.0** (Kern und DICOM-Viewer) · Audit-Export: **3.1.0**.

SMDG ermöglicht Ärzten, Kliniken und Patienten den sicheren Austausch
medizinischer Dateien. Jede Datei wird serverseitig mit
[age](https://age-encryption.org/) verschlüsselt, über zeitlich begrenzte
Einmal-Links geschützt, mit ClamAV geprüft und vollständig auditiert. Ein
eingebauter DICOM-Viewer rendert Studien im Browser, ohne entschlüsselte
Daten an den Client zu senden.

## Dokumentation

Die vollständige Dokumentation für Anwender und Betreiber liegt unter
[`docs/`](docs/README.md). Die englische Version in
[`docs/src/`](docs/src/) ist die Quelle der Wahrheit, Übersetzungen
folgen in [`docs/locales/{ru,de,fr}/`](docs/locales/).

- Übersicht — [`docs/locales/de/README.md`](docs/locales/de/README.md)
- API-Leitfaden — [`docs/locales/de/API_GUIDE.md`](docs/locales/de/API_GUIDE.md)
- Architektur — [`docs/locales/de/ARCHITECTURE.md`](docs/locales/de/ARCHITECTURE.md)
- Deployment-Profile — [`docs/locales/de/DEPLOYMENT.md`](docs/locales/de/DEPLOYMENT.md)
- DICOM-Viewer — [`docs/locales/de/DICOM_VIEWER.md`](docs/locales/de/DICOM_VIEWER.md)
- Sicherheit — [`docs/locales/de/SECURITY.md`](docs/locales/de/SECURITY.md)

## Schnellstart

```bash
git clone <ihr-repo>
cd smdg
cp .env.example .env
docker compose up --build
```

Öffnen Sie <https://localhost>. Standard-Entwicklungs-Zugangsdaten:
`admin` / `admin` (sofort ändern).

## Deployment-Profile

Die Umgebungsvariable `DEPLOYMENT_TYPE` wählt die Feature-Matrix:

| Profil   | Zusammenfassung                                                              |
|----------|------------------------------------------------------------------------------|
| `russia` | FZ-152-konform: lokaler Speicher, obligatorisches 2FA, 3 Jahre Audit         |
| `intl`   | S3/MinIO, DICOM, GDPR/HIPAA-orientierte Funktionen                           |
| `single` | Einzel-Mandant, vereinfachte Admin-Oberfläche, lokale Platte als Standard    |
| `saas`   | Multi-Mandant, Abrechnung / White-Label, Objektspeicher                      |

Details: [`docs/locales/de/DEPLOYMENT.md`](docs/locales/de/DEPLOYMENT.md).

## Mehrsprachigkeit

- Web-UI: English / Русский / Deutsch / Français mit Sprachumschalter
  (siehe [`static/js/i18n.js`](static/js/i18n.js)).
- API-Dokumentation: `/docs` (Englisch), `/docs/ru`, `/docs/de`, `/docs/fr`
  und `/openapi.{ru,de,fr}.json`.
- Benutzerdokumentation: `docs/src/` (Englisch) + `docs/locales/<lang>/`.

## Lizenz

MIT. Autor: Valeriy Popov.
