<!-- smdg-i18n-header-start
source: docs/src/README.md
source_sha1: 231cd132ac83d5971a90dcb1e979cea1ab468499
language: fr
last_sync: 2026-05-31
status: translated
smdg-i18n-header-end -->

# Secure Medical Data Gateway (SMDG)

**Transfert sécurisé de fichiers médicaux avec chiffrement de bout en bout**

**Version actuelle :** **4.0.0** (cœur et visionneuse DICOM) ; export d'audit — **3.1.0**.

SMDG est une solution auto-hébergée pour l'échange sécurisé de données
médicales entre médecins, cliniques et patients. Tous les fichiers sont
chiffrés sur le serveur, protégés par des liens à durée limitée et consignés
dans une piste d'audit complète.

Les guides détaillés se trouvent sous **[docs/](../../README.md)** — voir le
tableau de la section « Documentation » ci-dessous.

---

## Fonctionnalités

### Cœur (v1.0)

- Chiffrement de bout en bout des fichiers avec **age**
- Validation du type de fichier (vérifications MIME et extension) avant le chiffrement
- **JWT** + cookies HttpOnly
- Authentification à deux facteurs (**TOTP** / 2FA)
- Contrôle d'accès basé sur les rôles (**RBAC**) : `admin` | `doctor` | `user` | `super_admin` (multi-tenant)
- **Limitation de débit** (slowapi + **Redis**)
- **Audit** complet des opérations (**JSON** par jour + **CSV** avec rotation)
- **Export d'audit** pour les administrateurs : **Excel**, **PDF**, **CSV** sur une période avec filtres ([API](API_GUIDE.md#api-dexport-daudit))
- Interface web pratique + panneau d'administration
- Nettoyage automatique des anciens fichiers et rotation des clés de chiffrement
- **Docker** + **Docker Secrets**

### Stockage (v2.0)

- Abstraction **StorageBackend** : **LocalStorageBackend** et **S3StorageBackend**
- Fournisseurs compatibles S3 : **MinIO**, **Yandex Object Storage**, **Selectel**, **AWS S3**, **DigitalOcean Spaces**
- **Politiques de cycle de vie S3** (suppression automatique selon des règles TTL)
- Script de migration FS → S3 (`scripts/migrate_to_s3.py`)

### Webhooks (v2.1)

- Événements : `file.uploaded`, `file.downloaded`, `file.deleted`
- Charge utile signée avec **HMAC-SHA256**, nouvelles tentatives avec **backoff exponentiel**
- Historique et statuts de livraison persistés dans la base de données

### Visionneuse DICOM (v3.0)

- Rendu côté serveur avec **pydicom** + **numpy** + **PIL** → PNG
- Multi-frame (**CT/IRM**) avec mode **Cine**
- Préréglages **Window/Level** (Bone, Lung, Brain, Abdomen, Liver)
- Mesures : règle, angle, ROI (rectangle / ellipse)
- Export PNG / captures d'écran avec annotations
- **DICOMweb** : **QIDO-RS** + **WADO-RS**
- Intégration de visionneuse de style **OHIF**
- **Redis** : mise en cache des métadonnées et des PNG

Voir [DICOM_VIEWER.md](DICOM_VIEWER.md) pour les détails.

---

## Configuration minimale

**Pour le développement et l'exécution en local :**

| Exigence              | Minimum                      | Recommandé              |
|-----------------------|------------------------------|-------------------------|
| Docker + Compose      | Docker 24+, Compose v2       | Docker Desktop 4.20+    |
| Python                | 3.10+                        | 3.12.x                  |
| RAM                   | 4 Go                         | 8 Go+                   |
| CPU                   | 2 cœurs                      | 4+ cœurs                |
| Disque                | 10 Go libres                 | 20 Go+ (SSD)            |
| OS                    | Linux / macOS / Windows+WSL2 | Ubuntu 22.04 / 24.04    |

**Pour la production :** PostgreSQL 15+, Redis 7+, 8 Go+ de RAM.

---

## Démarrage rapide

### Local (développement)

```bash
git clone <your-repo>
cd smdg

cp .env.example .env
docker compose up --build
```

Application : **https://localhost** (ou le port HTTP défini dans compose).

### Production

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

### Exécution avec MinIO (S3)

```bash
# Dans .env :
S3_ENABLED=true
S3_ACCESS_KEY=minioadmin
S3_SECRET_KEY=minioadmin123

docker compose --profile s3 up -d
```

Console MinIO : http://localhost:9001

### Migration de données FS → S3

```bash
python scripts/migrate_to_s3.py --dry-run
python scripts/migrate_to_s3.py --delete-local
```

---

## Profils de déploiement (feature flags)

Une seule base de code prend en charge plusieurs profils via
**`DEPLOYMENT_TYPE`** (`russia` | `intl` | `single` | `saas` | `demo`) : la
matrice des fonctionnalités se trouve dans `app/core/feature_flags.py`, les
vérifications à l'exécution sous `GET /health/features` et la CLI
`python -m app.cli feature-info`.

| Profil   | Résumé                                                                                               |
|----------|-----------------------------------------------------------------------------------------------------|
| `russia` | Loi russe sur la protection des données (FZ-152) : stockage local, DICOM, 2FA obligatoire, audit 3 ans, prêt pour GOST |
| `intl`   | S3/MinIO, DICOM, fonctionnalités orientées RGPD/HIPAA, 2FA                                          |
| `single` | Tenant unique, admin simplifié, DICOM, 2FA, disque local par défaut                                 |
| `saas`   | Multi-tenant, facturation/marque blanche dans la matrice, stockage objet, DICOM, 2FA                |
| `demo`   | Démonstration publique : stockage local, 2FA facultative, DICOM, fonctionnalités RGPD/HIPAA, petite limite de téléversement, réinitialisation des données toutes les 24 h |

Voir [DEPLOYMENT.md](DEPLOYMENT.md) et la liste complète des fonctionnalités dans [FEATURES.md](FEATURES.md).

---

## Organisation du projet

```
smdg/
├── app/
│   ├── api/                    # REST : upload, download, auth, admin, webhooks, dicom,
│   │                           # admin_audit_export
│   ├── core/                   # config, DB, sécurité, storage_backend, audit, audit_export
│   ├── crypto/                 # age : chiffrement / rotation des clés
│   ├── models/                 # SQLModel : User, File, FileLink, Tenant, Webhook, DICOM …
│   └── main.py                 # FastAPI, lifespan, middleware
├── static/                     # HTML, JS, CSS (frontend)
├── audit_logs/                 # JSON audit_YYYY-MM-DD.log + CSV (voir AUDIT_LOGS_DIR)
├── encrypted/
├── decrypted/
├── keys/
├── migrations/
├── tests/
├── docs/                       # Architecture, API, déploiement, DICOM, SECURITY …
├── docker-compose.yml
├── docker-compose.prod.yml
├── Dockerfile
├── entrypoint.sh
├── pyproject.toml
└── README.md
```

| Fichier                         | Rôle                                  |
|---------------------------------|---------------------------------------|
| `app/main.py`                   | Lifespan, middleware, routeurs        |
| `app/core/config.py`            | Paramètres (Pydantic Settings)        |
| `app/core/audit_export.py`      | Lecture des logs, export Excel/PDF/CSV |
| `app/api/admin_audit_export.py` | `GET /api/admin/audit/export`         |
| `app/core/storage_backend.py`   | Local / S3                            |
| `scripts/migrate_to_s3.py`      | Migration vers le stockage objet      |

---

## Sécurité et conformité

- Chiffrement avec **age**, mots de passe hachés avec **Argon2**, JWT stockés dans des cookies **HttpOnly**
- Politique : [SECURITY.md](SECURITY.md)
- Modèle de conformité (FZ-152 / RGPD) : [COMPLIANCE_TEMPLATE.md](COMPLIANCE_TEMPLATE.md)

---

## Documentation

| Document                                     | Description                                         |
|----------------------------------------------|-----------------------------------------------------|
| [API_GUIDE.md](API_GUIDE.md)                 | API : authentification, limites, DICOM, export d'audit |
| [ARCHITECTURE.md](ARCHITECTURE.md)           | Architecture, ERD, diagrammes                       |
| [DEPLOYMENT.md](DEPLOYMENT.md)               | Déploiement, dépendances de l'export d'audit        |
| [DICOM_VIEWER.md](DICOM_VIEWER.md)           | Visionneuse DICOM                                   |
| [MULTI_TENANCY.md](MULTI_TENANCY.md)         | Multi-tenancy                                       |
| [CHANGELOG.md](CHANGELOG.md)                 | Historique des versions                             |
| [SECURITY.md](SECURITY.md)                   | Politique de sécurité                               |
| [TESTING.md](TESTING.md)                     | Stratégie de test                                   |
| [CONTRIBUTING.md](CONTRIBUTING.md)           | Guide de contribution                               |
| [COMPLIANCE_TEMPLATE.md](COMPLIANCE_TEMPLATE.md) | Modèle de conformité FZ-152 / RGPD              |

---

## Interfaces

| Interface  | URL        |
|------------|------------|
| Web UI     | `/`        |
| Admin      | `/admin`   |
| Swagger    | `/docs`    |
| Health     | `/health`  |
| Métriques  | `/metrics` |

---

## Licence

MIT. Auteur : Valeriy Popov.

SMDG — votre passerelle sécurisée pour les données médicales.
