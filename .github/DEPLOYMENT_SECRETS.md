# GitHub Actions: секреты для деплоя на VPS

Справка для настройки репозитория. Workflow: [`workflows/deploy.yml`](workflows/deploy.yml) — **два VPS** параллельно при push в `main`.

## Простой деплой — общие секреты

| Name | Описание |
|------|----------|
| `VPS_SSH_KEY` | Приватный SSH-ключ (один на **оба** сервера; публичная часть в `authorized_keys` на каждом VPS) |
| `VPS_GITHUB_TOKEN` | Опционально: PAT для `git clone`, если включён `VPS_AUTO_CLONE` / `VPS2_AUTO_CLONE` и репозиторий приватный |

## Сервер 1 (primary)

| Name | Описание |
|------|----------|
| `VPS_HOST` | IP или hostname |
| `VPS_USER` | SSH-пользователь |

| Variable | По умолчанию |
|----------|----------------|
| `VPS_DEPLOY_PATH` | `/home/smdg/SMDG` |
| `VPS_AUTO_CLONE` | `true` — автоматический clone, если каталога ещё нет |

## Сервер 2 (fileguardian — 74.208.252.225)

| Name | Описание |
|------|----------|
| `VPS2_HOST` | `74.208.252.225` (или hostname, если резолвится с runner Actions) |
| `VPS2_USER` | SSH-пользователь (часто `ubuntu` при пути `/home/ubuntu/SMDG`) |

| Variable | По умолчанию |
|----------|----------------|
| `VPS2_DEPLOY_PATH` | `/home/ubuntu/SMDG` |
| `VPS2_AUTO_CLONE` | как на первом сервере, при необходимости |
| `VPS2_DOMAIN` | опционально переопределить домен для smoke-теста (по умолчанию `fileguardian.info`) |

После деплоя для **fileguardian** workflow проверяет `https://<domain>/health/ready`.

Перед первым запуском на каждом VPS: Docker, clone в `DEPLOY_PATH`, каталог `secrets/`, `.env`, либо `VPS*_AUTO_CLONE=true`.

## Rolling / registry ([`workflows/deploy-rolling.yml`](workflows/deploy-rolling.yml))

Один prod-сервер (`DEPLOY_HOST`, `DEPLOY_DOMAIN`). Для второго VPS rolling нужен отдельный workflow или дублирование job — см. комментарий в начале `deploy-rolling.yml`.
