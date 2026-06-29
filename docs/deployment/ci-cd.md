# CI/CD

Автоматизация сборки, тестов и деплоя SMDG.

## Workflows

| Workflow | Триггер | Назначение |
|----------|---------|------------|
| `ci.yml` | PR, push | Тесты, lint, security scans |
| `deploy-primary.yml` | push main | Деплой на primary VPS |
| `deploy-fileguardian.yml` | push main | Деплой demo на fileguardian.info |
| `deploy-rolling.yml` | manual | Rolling update |
| `docs-build.yml` | push docs | Сборка MkDocs site |
| `docs-i18n.yml` | push docs | Проверка переводов src/locales |

## GitHub Secrets (primary)

| Secret | Пример |
|--------|--------|
| `VPS_HOST` | `186.246.3.65` |
| `VPS_USER` | `smdg` |
| `VPS_SSH_KEY` | приватный ключ deploy |

Полный список: [.github/DEPLOYMENT_SECRETS.md](../../.github/DEPLOYMENT_SECRETS.md).

## GitHub Secrets (demo / fileguardian)

| Secret | Пример |
|--------|--------|
| `VPS2_HOST` | `74.208.252.225` |
| `VPS2_DOMAIN` | `fileguardian.info` |

## Локальная проверка перед push

```bash
poetry run pytest
poetry run ruff check app tests
poetry run mkdocs build
```

## Документация в CI

При изменении `docs/**` или `mkdocs.yml` workflow `docs-build.yml` собирает `site/` и коммитит артефакт (как в MedInsight).

## Мониторинг деплоя

```bash
gh run list --workflow=deploy-primary.yml --limit 3
gh run watch
```

После деплоя:

```bash
curl -fsS https://fileguardian.info/health/ready
```
