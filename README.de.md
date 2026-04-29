[English](README.md) | [Русский](README.ru.md) | **Deutsch** | [Français](README.fr.md)

# SMDG — Secure Medical Data Gateway

**Selbstgehostetes Gateway für medizinische Dateien mit Ende-zu-Ende-Verschlüsselung.**

Version: **4.0.0** (Kern und DICOM-Viewer) · Audit-Export: **3.1.0**.

SMDG ermöglicht Ärzten, Kliniken und Patienten den sicheren Austausch
medizinischer Dateien. Jede Datei wird serverseitig mit
[age](https://age-encryption.org/) verschlüsselt, über zeitlich begrenzte
Einmal-Links geschützt und vollständig auditiert. Ein
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
- Runbook fuer horizontale Skalierung — [`docs/locales/de/DEPLOYMENT.md`](docs/locales/de/DEPLOYMENT.md#horizontale-skalierung-stateless-cluster)
- Runbook fuer Rueckkehr zum Ausgangszustand — [`docs/runbooks/rollback-to-baseline.md`](docs/runbooks/rollback-to-baseline.md)
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

Fuer stateless horizontale Skalierung (Redis fuer Sessions/Cache/Queue, Nginx
als Load Balancer, `/health/live` und `/health/ready`, Blue/Green-Cutover-
Skripte) verwenden Sie den Abschnitt **"Horizontale Skalierung (stateless
Cluster)"** im Deployment-Leitfaden.
Das Rollback zum Basiszustand ist in
[`docs/runbooks/rollback-to-baseline.md`](docs/runbooks/rollback-to-baseline.md)
beschrieben.

## Mehrsprachigkeit

- Web-UI: English / Русский / Deutsch / Français mit Sprachumschalter
  (siehe [`static/js/i18n.js`](static/js/i18n.js)).
- API-Dokumentation: `/docs` (Englisch), `/docs/ru`, `/docs/de`, `/docs/fr`
  und `/openapi.{ru,de,fr}.json`.
- Benutzerdokumentation: `docs/src/` (Englisch) + `docs/locales/<lang>/`.

## Security Scanning

Der CI-Workflow [`security-scan.yml`](.github/workflows/security-scan.yml) führt
SAST-, SCA-, Secret-, Container- und DAST-Scans für `push`, `pull_request`,
`schedule` und manuelle Ausführung aus.

### Automatische Modus-Umschaltung (`SECURITY_SCAN_MODE`)

Der Workflow wählt den Scan-Modus automatisch nach Event:

- `schedule` -> `audit`
- `push` / `pull_request` / `workflow_dispatch` -> `balanced` (Standard)
- Für nicht-geplante Events kann per Repository-Variable
  `SECURITY_SCAN_MODE=strict` (oder `balanced`) überschrieben werden

Effektiver Ausdruck im Workflow:

```yaml
env:
  SECURITY_SCAN_MODE: ${{ github.event_name == 'schedule' && 'audit' || (vars.SECURITY_SCAN_MODE == 'strict' && 'strict' || 'balanced') }}
```

So setzen Sie die Repository-Variable in GitHub:

1. Repository öffnen -> **Settings** -> **Secrets and variables** -> **Actions**.
2. Zum Tab **Variables** wechseln.
3. **New repository variable** anklicken.
4. Setzen:
   - Name: `SECURITY_SCAN_MODE`
   - Value: `strict` (oder `balanced`)

Beispiel mit GitHub CLI:

```bash
gh variable set SECURITY_SCAN_MODE --body strict
```

## Lizenz

MIT. Autor: Valeriy Popov.
