# GitHub Actions: секреты для деплоя на VPS

Не редактируйте этот файл вручную для CI — он служит справкой для настройки репозитория.

## Простой деплой ([`workflows/deploy.yml`](workflows/deploy.yml))

**Secrets** (Settings → Secrets and variables → Actions):

| Name | Описание |
|------|----------|
| `VPS_HOST` | IP или hostname VPS |
| `VPS_USER` | SSH-пользователь |
| `VPS_SSH_KEY` | Приватный ключ SSH (полный PEM), пара к `authorized_keys` на сервере |
| `VPS_GITHUB_TOKEN` | Опционально: PAT только для первого `git clone` на VPS, если включён `VPS_AUTO_CLONE` и репозиторий приватный |

**Variables** (optional):

| Name | По умолчанию |
|------|----------------|
| `VPS_DEPLOY_PATH` | `/home/smdg/SMDG` — каталог с клоном репозитория на VPS |
| `VPS_AUTO_CLONE` | Если `true` и каталога ещё нет — workflow выполнит `mkdir -p` и `git clone` (для публичного репозитория PAT не нужен) |

Перед первым запуском на VPS должен существовать каталог с clone репозитория **или** включите `VPS_AUTO_CLONE=true`. Если clone уже лежит в другом месте (например `/home/ubuntu/SMDG`), задайте `VPS_DEPLOY_PATH` без правки workflow.

## Rolling / registry ([`workflows/deploy-rolling.yml`](workflows/deploy-rolling.yml))

См. комментарий в начале workflow: Docker Hub, `DEPLOY_*`, Environment `production`.
