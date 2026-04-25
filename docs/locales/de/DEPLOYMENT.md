<!-- smdg-i18n-header-start
source: docs/src/DEPLOYMENT.md
source_sha1: b23f0469215797d128b33765288f7ea12ec45b97
language: de
last_sync: 2026-04-25
status: translated
smdg-i18n-header-end -->

# SMDG Deployment-Profile

Die Umgebungsvariable **`DEPLOYMENT_TYPE`** akzeptiert:
`russia` | `intl` | `single` | `saas`.

## Russia (`russia`)

- Lokaler Speicher (`S3_ENABLED=false`).
- Verpflichtendes 2FA auf Ebene der Login-Policy.
- Audit-Aufbewahrung: 1095 Tage (`AUDIT_3_YEARS` in der Matrix).
- GOST-Kryptoprofil (`GOST_CRYPTO`): aktuell ein Wrapper um `age`;
  vor Produktion durch einen zertifizierten Anbieter ersetzen.

```bash
docker build --build-arg DEPLOYMENT_TYPE=russia -t smdg:russia .
docker compose -f docker-compose.yml -f docker-compose.russia.yml up -d
```

## International (`intl`)

- S3 / MinIO, DICOM-Viewer und GDPR-orientierte Features sind aktiviert.

```bash
DEPLOYMENT_TYPE=intl docker compose up -d
```

Verwenden Sie das Overlay `docker-compose.intl.yml`, um Ressourcenlimits
anzuwenden.

## Single tenant (`single`)

- Ein Standard-Mandant, vereinfachtes Admin-Panel (`SIMPLE_ADMIN`), lokaler
  Speicher standardmaessig.
- Mit deaktiviertem `MULTI_TENANCY` kann die Rolle `super_admin` die
  Organisation nicht ueber `Host` oder `X-Tenant-*` wechseln: der Kontext wird
  immer ueber `tenant_default_subdomain` aufgeloest.

```bash
docker compose -f docker-compose.yml -f docker-compose.single.yml up -d
```

Wenn `.env` bereits S3 mit gueltigen Zugangsdaten aktiviert, bleibt die
Rueckwaertskompatibilitaet erhalten und S3 wird weiter genutzt.

## SaaS (`saas`)

- Multi-Tenancy, Billing und White-Label sind aktiv; ausserhalb von Dev wird
  ein funktionierendes S3-Backend benoetigt.

```bash
docker compose -f docker-compose.yml -f docker-compose.saas.yml up -d
```

## Horizontale Skalierung (stateless Cluster)

Verwenden Sie `docker-compose.scale.yml`, wenn mehrere App-Replikas hinter
einem Nginx-Load-Balancer benoetigt werden.

### Architektur-Anforderungen

- App-Knoten muessen stateless bleiben.
- Sessions, Cache und Job-Queue in Redis speichern:
  - `HORIZONTAL_SCALING_REDIS_SESSION_URL`
  - `HORIZONTAL_SCALING_REDIS_CACHE_URL`
  - `HORIZONTAL_SCALING_REDIS_JOB_QUEUE_URL`
- Fuer Uploads gemeinsamen Objektspeicher (`S3`/`MinIO`) verwenden.
- Eingehenden Traffic ueber `nginx-lb`
  (`nginx/nginx-load-balancer.conf`) routen.

### Start und Skalierung

```bash
# Basiskonfiguration starten (Ports: 18080 HTTP, 18443 HTTPS)
docker compose -p smdg-scale -f docker-compose.scale.yml up -d

# Auf 3 App-Replikas skalieren
docker compose -p smdg-scale -f docker-compose.scale.yml up -d --scale smdg=3

# Oder Helper-Skript nutzen
./scripts/scale.sh 3
```

### Readiness und Lastverteilung pruefen

```bash
# Cluster-Readiness ueber Load-Balancer
curl -k https://localhost:18443/health/ready

# Verteilung ueber Replikas pruefen
for i in {1..30}; do
  curl -ks https://localhost:18443/health/ready | jq -r '.instance_id'
done | sort | uniq -c
```

`/health/live` fuer Liveness-Probes, `/health/ready` fuer Orchestrator-Routing,
`/health/metrics` fuer instance-spezifische Betriebsmetriken.

### Blue/green Cutover

**Skalierter Cluster** (`smdg-scale`, `docker-compose.scale.yml`): `./scripts/cutover.sh`
kopiert Upstream-Fragmente aus `nginx/upstreams/` nach
`nginx/nginx-load-balancer.conf`, prueft die Konfiguration und laedt
`nginx-lb` neu. Modi: `status`, `blue` (alle Replikas), `green <n>` (nur
Replika *n*), `canary`, `rollback`.

```bash
./scripts/cutover.sh status
./scripts/cutover.sh blue
./scripts/cutover.sh green 2
```

`./scripts/deploy.sh` baut den App-Container und ruft bei Erfolg
`./scripts/cutover.sh green <Instanz>` auf.

**Include-basiert** (mit `include ... upstream-target.conf` und
`proxy_pass $smdg_upstream;`):

```bash
./scripts/cutover_include.sh blue
./scripts/cutover_include.sh green
```

**Edge-Container** (Upstream-Tausch in einem einzelnen Nginx, ohne
Scale-Compose-Datei):

```bash
EDGE_NGINX_CONTAINER=smdg-nginx-1 ./scripts/cutover_edge.sh
```

Include- und Edge-Skripte pruefen Nginx, laden neu, post-cutover Health-Check
und Auto-Rollback (Umgebungsvariablen: Kommentar im Skript).

Dediziertes Rollback-Runbook:
[`docs/runbooks/rollback-to-baseline.md`](../../runbooks/rollback-to-baseline.md).

## Migration von aelteren Versionen

1. Setzen Sie `DEPLOYMENT_TYPE` (fuer den aktuellen Docker-Stack mit MinIO ist
   `intl` empfohlen).
2. Führen Sie `python scripts/migrate_deployment_type.py --target <type>` fuer
   eine Migrations-Checkliste aus.
3. Dienste neu starten.

`.env`-Vorlagen: `.env.<profile>.example` im Repository-Root.

## Betriebs-Runbooks

- Hauptindex: [`docs/runbooks/README.md`](../../runbooks/README.md)
- Taegliche Checks: [`docs/runbooks/operations/daily-checks.md`](../../runbooks/operations/daily-checks.md)
- Woechentliche Wartung: [`docs/runbooks/operations/weekly-maintenance.md`](../../runbooks/operations/weekly-maintenance.md)
- Monatliche Aufgaben: [`docs/runbooks/operations/monthly-tasks.md`](../../runbooks/operations/monthly-tasks.md)
- Backup und Wiederherstellung: [`docs/runbooks/operations/backup-recovery.md`](../../runbooks/operations/backup-recovery.md)
