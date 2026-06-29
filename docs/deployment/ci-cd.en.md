# CI/CD

SMDG build, test and deploy automation.

## Workflows

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| `ci.yml` | PR, push | Tests, lint, security scans |
| `deploy-primary.yml` | push main | Deploy to primary VPS |
| `deploy-fileguardian.yml` | push main | Deploy demo to fileguardian.info |
| `deploy-rolling.yml` | manual | Rolling update |
| `docs-build.yml` | push docs | Build MkDocs site |
| `docs-i18n.yml` | push docs | Validate src/locales translations |

## GitHub Secrets (primary)

| Secret | Example |
|--------|---------|
| `VPS_HOST` | `186.246.3.65` |
| `VPS_USER` | `smdg` |
| `VPS_SSH_KEY` | deploy private key |

Full list: [.github/DEPLOYMENT_SECRETS.md](../../.github/DEPLOYMENT_SECRETS.md).

## GitHub Secrets (demo / fileguardian)

| Secret | Example |
|--------|---------|
| `VPS2_HOST` | `74.208.252.225` |
| `VPS2_DOMAIN` | `fileguardian.info` |

## Local pre-push checks

```bash
poetry run pytest
poetry run ruff check app tests
poetry run mkdocs build
```

## Docs in CI

On changes to `docs/**` or `mkdocs.yml`, workflow `docs-build.yml` builds `site/` and commits the artefact (same pattern as MedInsight).

## Monitor deploy

```bash
gh run list --workflow=deploy-primary.yml --limit 3
gh run watch
```

After deploy:

```bash
curl -fsS https://fileguardian.info/health/ready
```
