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

### Ошибка `Permission denied (publickey,password)` на fileguardian

В логе Actions шаг **«SSH agent»** печатает строку `ssh-add -L` — **именно её** (одна строка) нужно добавить в `authorized_keys` на втором VPS. Локально ту же строку даёт:

```bash
chmod +x scripts/show-deploy-ssh-pubkey.sh
./scripts/show-deploy-ssh-pubkey.sh /path/to/тот_же_приватный_ключ
```

Один и тот же **`VPS_SSH_KEY`** должен быть принят на **обоих** серверах, но у **разных пользователей**, если пути разные:

| Сервер | Типичный `VPS*_USER` | `authorized_keys` |
|--------|----------------------|-------------------|
| primary | `smdg` | `/home/smdg/.ssh/authorized_keys` |
| fileguardian | **`ubuntu`** (не `smdg`) | `/home/ubuntu/.ssh/authorized_keys` |

На **74.208.252.225** под пользователем из `VPS2_USER`:

```bash
mkdir -p ~/.ssh && chmod 700 ~/.ssh
# вставьте одну строку публичного ключа (пара к VPS_SSH_KEY)
nano ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

Проверка локально (тот же приватный ключ, что в GitHub Secret):

```bash
ssh -i ~/.ssh/id_rsa -o BatchMode=yes ubuntu@74.208.252.225 'hostname'
```

В GitHub Secrets: **`VPS2_USER`** = `ubuntu`, **`VPS2_HOST`** = `74.208.252.225`. Лишние пробелы/переносы в `VPS_SSH_KEY` ломают вход — в Secret только тело ключа, включая `-----BEGIN...-----`.

## Rolling / registry ([`workflows/deploy-rolling.yml`](workflows/deploy-rolling.yml))

Один prod-сервер (`DEPLOY_HOST`, `DEPLOY_DOMAIN`). Для второго VPS rolling нужен отдельный workflow или дублирование job — см. комментарий в начале `deploy-rolling.yml`.
