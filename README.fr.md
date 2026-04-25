[English](README.md) | [Русский](README.ru.md) | [Deutsch](README.de.md) | **Français**

# SMDG — Secure Medical Data Gateway

**Passerelle auto-hébergée pour l'échange de fichiers médicaux chiffrés de bout en bout.**

Version : **4.0.0** (cœur et visualiseur DICOM) · export d'audit : **3.1.0**.

SMDG permet aux médecins, cliniques et patients d'échanger en toute
sécurité des fichiers médicaux. Chaque fichier est chiffré côté serveur
avec [age](https://age-encryption.org/), protégé par des liens uniques
à durée limitée, analysé par ClamAV et entièrement journalisé dans
l'audit. Le visualiseur DICOM intégré affiche les études dans le
navigateur sans transmettre de données déchiffrées au client.

## Documentation

La documentation complète pour les utilisateurs et les opérateurs se
trouve dans [`docs/`](docs/README.md). La source de vérité est la
version anglaise sous [`docs/src/`](docs/src/), les traductions dans
[`docs/locales/{ru,de,fr}/`](docs/locales/).

- Vue d'ensemble — [`docs/locales/fr/README.md`](docs/locales/fr/README.md)
- Guide API — [`docs/locales/fr/API_GUIDE.md`](docs/locales/fr/API_GUIDE.md)
- Architecture — [`docs/locales/fr/ARCHITECTURE.md`](docs/locales/fr/ARCHITECTURE.md)
- Profils de déploiement — [`docs/locales/fr/DEPLOYMENT.md`](docs/locales/fr/DEPLOYMENT.md)
- Runbook de mise a l'echelle horizontale — [`docs/locales/fr/DEPLOYMENT.md`](docs/locales/fr/DEPLOYMENT.md#mise-a-lechelle-horizontale-cluster-stateless)
- Runbook de retour a l'etat initial — [`docs/runbooks/rollback-to-baseline.md`](docs/runbooks/rollback-to-baseline.md)
- Visualiseur DICOM — [`docs/locales/fr/DICOM_VIEWER.md`](docs/locales/fr/DICOM_VIEWER.md)
- Sécurité — [`docs/locales/fr/SECURITY.md`](docs/locales/fr/SECURITY.md)

## Démarrage rapide

```bash
git clone <votre-depot>
cd smdg
cp .env.example .env
docker compose up --build
```

Ouvrez <https://localhost>. Identifiants de dev par défaut : `admin` /
`admin` (à changer immédiatement).

## Profils de déploiement

La variable d'environnement `DEPLOYMENT_TYPE` choisit la matrice :

| Profil   | Résumé                                                                      |
|----------|-----------------------------------------------------------------------------|
| `russia` | Conforme FZ-152 : stockage local, 2FA obligatoire, audit 3 ans              |
| `intl`   | S3/MinIO, DICOM, fonctions orientées GDPR/HIPAA                             |
| `single` | Locataire unique, admin simplifiée, disque local par défaut                 |
| `saas`   | Multi-locataire, facturation / white-label, stockage objet                  |

Détails : [`docs/locales/fr/DEPLOYMENT.md`](docs/locales/fr/DEPLOYMENT.md).

Pour la mise a l'echelle horizontale stateless (Redis pour sessions/cache/file
de jobs, Nginx load balancer, probes `/health/live` et `/health/ready`, scripts
de cutover blue/green), utilisez la section **"Mise a l'echelle horizontale
(cluster stateless)"** du guide de deploiement.
La procedure de retour au baseline est decrite dans
[`docs/runbooks/rollback-to-baseline.md`](docs/runbooks/rollback-to-baseline.md).

## Support multilingue

- Interface web : English / Русский / Deutsch / Français avec sélecteur
  de langue (voir [`static/js/i18n.js`](static/js/i18n.js)).
- Documentation API : `/docs` (anglais), `/docs/ru`, `/docs/de`,
  `/docs/fr` et `/openapi.{ru,de,fr}.json`.
- Documentation utilisateur : `docs/src/` (anglais) + `docs/locales/<lang>/`.

## Security Scanning

Le workflow CI [`security-scan.yml`](.github/workflows/security-scan.yml) exécute
les scans SAST, SCA, secrets, conteneur et DAST pour `push`, `pull_request`,
`schedule` et l'exécution manuelle.

### Bascule automatique du mode (`SECURITY_SCAN_MODE`)

Le workflow sélectionne automatiquement le mode selon l'événement :

- `schedule` -> `audit`
- `push` / `pull_request` / `workflow_dispatch` -> `balanced` (par défaut)
- Pour les événements non planifiés, surcharge possible via la variable
  de dépôt `SECURITY_SCAN_MODE=strict` (ou `balanced`)

Expression effective dans le workflow :

```yaml
env:
  SECURITY_SCAN_MODE: ${{ github.event_name == 'schedule' && 'audit' || (vars.SECURITY_SCAN_MODE == 'strict' && 'strict' || 'balanced') }}
```

Comment configurer la variable de dépôt dans GitHub :

1. Ouvrez le dépôt -> **Settings** -> **Secrets and variables** -> **Actions**.
2. Allez à l'onglet **Variables**.
3. Cliquez sur **New repository variable**.
4. Définissez :
   - Name: `SECURITY_SCAN_MODE`
   - Value: `strict` (ou `balanced`)

Exemple via GitHub CLI :

```bash
gh variable set SECURITY_SCAN_MODE --body strict
```

## Licence

MIT. Auteur : Valeriy Popov.
