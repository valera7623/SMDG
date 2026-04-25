<!-- smdg-i18n-header-start
source: docs/src/DEPLOYMENT.md
source_sha1: b23f0469215797d128b33765288f7ea12ec45b97
language: fr
last_sync: 2026-04-25
status: translated
smdg-i18n-header-end -->

# Profils de deploiement SMDG

La variable d'environnement **`DEPLOYMENT_TYPE`** accepte:
`russia` | `intl` | `single` | `saas`.

## Russia (`russia`)

- Stockage local (`S3_ENABLED=false`).
- 2FA obligatoire appliquee au niveau de la politique de connexion.
- Retention d'audit: 1095 jours (`AUDIT_3_YEARS` dans la matrice).
- Profil crypto GOST (`GOST_CRYPTO`): actuellement un wrapper autour de `age`;
  remplacez-le par un fournisseur certifie avant la production.

```bash
docker build --build-arg DEPLOYMENT_TYPE=russia -t smdg:russia .
docker compose -f docker-compose.yml -f docker-compose.russia.yml up -d
```

## International (`intl`)

- S3 / MinIO, visualiseur DICOM, fonctionnalites orientees GDPR actives.

```bash
DEPLOYMENT_TYPE=intl docker compose up -d
```

Utilisez l'overlay `docker-compose.intl.yml` pour appliquer des limites
de ressources.

## Single tenant (`single`)

- Un locataire par defaut, panneau admin simplifie (`SIMPLE_ADMIN`), stockage
  local par defaut.
- Avec `MULTI_TENANCY` desactive, le role `super_admin` ne peut pas changer
  d'organisation via `Host` ou les en-tetes `X-Tenant-*`: le contexte est
  toujours resolu vers `tenant_default_subdomain`.

```bash
docker compose -f docker-compose.yml -f docker-compose.single.yml up -d
```

Si `.env` active deja S3 avec des identifiants valides, l'application conserve
la compatibilite et continue a utiliser S3.

## SaaS (`saas`)

- Multi-tenant, facturation et white-label actifs; un backend S3 fonctionnel
  est requis hors dev.

```bash
docker compose -f docker-compose.yml -f docker-compose.saas.yml up -d
```

## Mise a l'echelle horizontale (cluster stateless)

Utilisez `docker-compose.scale.yml` quand vous avez besoin de plusieurs
repliques d'application derriere un load balancer Nginx.

### Exigences d'architecture

- Les noeuds applicatifs doivent rester stateless.
- Stockez sessions, cache et file de jobs dans Redis:
  - `HORIZONTAL_SCALING_REDIS_SESSION_URL`
  - `HORIZONTAL_SCALING_REDIS_CACHE_URL`
  - `HORIZONTAL_SCALING_REDIS_JOB_QUEUE_URL`
- Utilisez un stockage objet partage (`S3`/`MinIO`) pour les fichiers.
- Faites passer tout le trafic entrant via `nginx-lb`
  (`nginx/nginx-load-balancer.conf`).

### Demarrage et scaling

```bash
# Demarrage de base (ports: 18080 HTTP, 18443 HTTPS)
docker compose -p smdg-scale -f docker-compose.scale.yml up -d

# Passage a 3 repliques
docker compose -p smdg-scale -f docker-compose.scale.yml up -d --scale smdg=3

# Ou avec le script utilitaire
./scripts/scale.sh 3
```

### Verification readiness et repartition

```bash
# Readiness du cluster via le load balancer
curl -k https://localhost:18443/health/ready

# Verifier la repartition entre repliques
for i in {1..30}; do
  curl -ks https://localhost:18443/health/ready | jq -r '.instance_id'
done | sort | uniq -c
```

Utilisez `/health/live` pour les probes de liveness, `/health/ready` pour le
routing orchestrateur et `/health/metrics` pour les metriques par instance.

### Cutover blue/green

**Cluster a l'echelle** (`smdg-scale`, `docker-compose.scale.yml`) : le script
`./scripts/cutover.sh` copie les amonts depuis `nginx/upstreams/` vers
`nginx/nginx-load-balancer.conf`, valide et recharge `nginx-lb`. Modes :
`status`, `blue` (toutes les repliques), `green <n>` (uniquement la replique *n*),
`canary`, `rollback`.

```bash
./scripts/cutover.sh status
./scripts/cutover.sh blue
./scripts/cutover.sh green 2
```

`./scripts/deploy.sh` reconstruit le service app puis appelle
`./scripts/cutover.sh green <instance>` lorsque le conteneur est sain.

**Base include** (layout avec `include ... upstream-target.conf` et
`proxy_pass $smdg_upstream;`):

```bash
./scripts/cutover_include.sh blue
./scripts/cutover_include.sh green
```

**Nginx edge** (remplacement d'amont in-place, sans le compose d'echelle) :

```bash
EDGE_NGINX_CONTAINER=smdg-nginx-1 ./scripts/cutover_edge.sh
```

Les variantes include et edge valident Nginx, rechargent, health-check
post-cutover et rollback auto (variables d'environnement : en-tete des scripts).

Runbook de rollback dedie:
[`docs/runbooks/rollback-to-baseline.md`](../../runbooks/rollback-to-baseline.md).

## Migration depuis une version plus ancienne

1. Definissez `DEPLOYMENT_TYPE` (pour la stack Docker actuelle avec MinIO, la
   valeur recommandee est `intl`).
2. Executez `python scripts/migrate_deployment_type.py --target <type>` pour
   obtenir la checklist de migration.
3. Redemarrez les services.

Modeles `.env`: `.env.<profile>.example` a la racine du depot.

## Runbooks d'exploitation

- Index principal: [`docs/runbooks/README.md`](../../runbooks/README.md)
- Verifications quotidiennes: [`docs/runbooks/operations/daily-checks.md`](../../runbooks/operations/daily-checks.md)
- Maintenance hebdomadaire: [`docs/runbooks/operations/weekly-maintenance.md`](../../runbooks/operations/weekly-maintenance.md)
- Taches mensuelles: [`docs/runbooks/operations/monthly-tasks.md`](../../runbooks/operations/monthly-tasks.md)
- Sauvegarde et restauration: [`docs/runbooks/operations/backup-recovery.md`](../../runbooks/operations/backup-recovery.md)
