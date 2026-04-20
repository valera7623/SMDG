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

## Support multilingue

- Interface web : English / Русский / Deutsch / Français avec sélecteur
  de langue (voir [`static/js/i18n.js`](static/js/i18n.js)).
- Documentation API : `/docs` (anglais), `/docs/ru`, `/docs/de`,
  `/docs/fr` et `/openapi.{ru,de,fr}.json`.
- Documentation utilisateur : `docs/src/` (anglais) + `docs/locales/<lang>/`.

## Licence

MIT. Auteur : Valeriy Popov.
