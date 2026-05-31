<!-- smdg-i18n-header-start
source: docs/src/FEATURES.md
source_sha1: 275e7dcf61cbf8cdb3b3ad6ecd16ec00e41b6d78
language: fr
last_sync: 2026-05-31
status: translated
smdg-i18n-header-end -->

# Carte des fonctionnalités SMDG (Feature Flags)

Les fonctionnalités sont activées par la `FEATURE_MATRIX` dans
`app/core/feature_flags.py` selon la valeur de `DEPLOYMENT_TYPE`
(`russia` | `intl` | `single` | `saas` | `demo`).

| Fonctionnalité           | Description                                                             |
|--------------------------|-------------------------------------------------------------------------|
| `dicom_viewer`           | Visionneuse DICOM (activée dans tous les profils)                      |
| `totp_2fa`               | Authentification à deux facteurs TOTP (disponible dans tous les profils) |
| `s3_storage`             | Stockage objet compatible S3                                           |
| `local_storage`          | Système de fichiers local                                              |
| `mandatory_2fa`          | Authentification à deux facteurs obligatoire                          |
| `gost_crypto`            | Mode GOST (stub étendu par un fournisseur certifié)                   |
| `audit_3_years`          | Conservation de l'audit pendant 1095 jours (sinon 365)               |
| `pacs_integration`       | Intégrations PACS                                                      |
| `gossopka`               | Intégration GosSOPKA (point d'extension)                              |
| `multi_tenancy`          | Isolation par tenant (SaaS)                                           |
| `billing`                | Facturation Stripe/Paddle (services externes)                         |
| `white_label`            | Personnalisation en marque blanche                                    |
| `right_to_be_forgotten`  | Procédures de droit à l'effacement (RGPD)                            |
| `data_portability`       | Export des données de la personne concernée                          |
| `auto_ssl`               | SSL automatique (reverse proxy / certbot — hors de l'application)     |
| `auto_backup`            | Sauvegardes (cron / sidecar)                                          |
| `simple_admin`           | Panneau d'administration simplifié dans l'UI                         |

Le profil `demo` est une variante de démonstration publique : stockage local
uniquement, 2FA facultative, visionneuse DICOM et fonctionnalités orientées
RGPD/HIPAA activées, petite limite de téléversement et réinitialisation
automatique des données. Voir [`docs/src/DEPLOYMENT.md`](DEPLOYMENT.md) et
`.env.demo.example`.

Vérifications à l'exécution :

- HTTP : `GET /health/features`, `GET /health/deployment`
- CLI : `python -m app.cli feature-info` (synthèse) et
  `python -m app.cli feature-check <feature>` (un seul indicateur)
