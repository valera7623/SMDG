# VPS

Deploying SMDG on a VPS.

## Requirements

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| CPU | 2 cores | 4+ |
| RAM | 4 GB | 8+ GB |
| Disk | 20 GB SSD | 50+ GB |
| OS | Ubuntu 22.04 / 24.04 | Ubuntu 24.04 LTS |

## Server setup

```bash
# Docker + Compose
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER

# Clone
git clone https://github.com/valera7623/SMDG.git /opt/smdg
cd /opt/smdg
```

## Configuration

```bash
cp .env.example .env
# Edit DOMAIN, LETSENCRYPT_EMAIL, DEPLOYMENT_TYPE
mkdir -p secrets
# Create secret files (see admin-guide/deployment.md)
```

## TLS (Let's Encrypt)

Production compose renews certificates automatically.

Manual renewal:

```bash
./scripts/renew_tls_certificates.sh
```

## Deploy

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

Zero-downtime:

```bash
./scripts/zero_downtime_deploy.sh
```

## Known VPS hosts

| Server | IP | Profile | Workflow |
|--------|-----|---------|----------|
| primary | 186.246.3.65 | production | `deploy-primary.yml` |
| fileguardian | 74.208.252.225 | demo | `deploy-fileguardian.yml` |

## Docs on VPS

Serve the static MkDocs site (`site/`) via Nginx:

```nginx
location /help/ {
    alias /opt/smdg/site/;
    try_files $uri $uri/ /help/index.html;
}
```

Build: `poetry run mkdocs build`

## Smoke test

```bash
BASE_URL=https://your-domain.com ./scripts/post-deploy-verify.sh
```
