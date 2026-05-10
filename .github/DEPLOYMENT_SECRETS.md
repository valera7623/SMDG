# GitHub Actions: секреты для деплоя на VPS

Не редактируйте этот файл вручную для CI — он служит справкой для настройки репозитория.

## Простой деплой ([`workflows/deploy.yml`](workflows/deploy.yml))

**Secrets** (Settings → Secrets and variables → Actions):

| Name | Описание |
|------|----------|
| `VPS_HOST` | IP или hostname VPS |
| `VPS_USER` | SSH-пользователь |
| `VPS_SSH_KEY` | Приватный ключ SSH (полный PEM), пара к `authorized_keys` на сервере |

**Variables** (optional):

| Name | По умолчанию |
|------|----------------|
| `VPS_DEPLOY_PATH` | `/home/smdg/SMDG` — каталог с клоном репозитория на VPS |

## Rolling / registry ([`workflows/deploy-rolling.yml`](workflows/deploy-rolling.yml))

См. комментарий в начале workflow: Docker Hub, `DEPLOY_*`, Environment `production`.
