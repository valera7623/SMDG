# GitHub Actions: секреты для деплоя на VPS

Справка для настройки репозитория. Workflow: [`workflows/deploy.yml`](workflows/deploy.yml) — **два VPS** параллельно при push в `main`.

## Простой деплой — общие секреты

| Name | Описание |
|------|----------|
| `VPS_SSH_KEY` | Приватный SSH-ключ целиком (`-----BEGIN ... PRIVATE KEY-----` … `-----END ...`). Без лишних кавычек и пробелов в начале. После смены Secret перезапустите workflow. |
| `VPS_GITHUB_TOKEN` | Опционально: PAT для `git clone`, если включён `VPS_AUTO_CLONE` / `VPS2_AUTO_CLONE` и репозиторий приватный |

## Сервер 1 (primary)

| Name | Описание |
|------|----------|
| `VPS_HOST` | IP или hostname |
| `VPS_USER` | SSH-пользователь (например `smdg`) |

| Variable | По умолчанию |
|----------|----------------|
| `VPS_DEPLOY_PATH` | `/home/smdg/SMDG` |
| `VPS_AUTO_CLONE` | `true` — автоматический clone, если каталога ещё нет |

## Сервер 2 (fileguardian — 74.208.252.225, https://fileguardian.info)

| Name | Описание |
|------|----------|
| `VPS2_HOST` | `74.208.252.225` (или hostname) |
| `VPS2_USER` | Обычно **`smdg`** (тот же пользователь, что на primary) |

| Variable | По умолчанию |
|----------|----------------|
| `VPS2_DEPLOY_PATH` | `/home/smdg/SMDG` — каталог с clone на втором VPS |
| `VPS2_AUTO_CLONE` | при необходимости |
| `VPS2_DOMAIN` | опционально (по умолчанию smoke-тест: `fileguardian.info`) |
| `VPS2_SSH_PROXY_JUMP` | для fileguardian: не `false` → SSH **через primary** (`ProxyJump` на `VPS_HOST`). Нужно, если с вашего ПК SSH работает, а GitHub Actions получает `Permission denied` / порт 22 закрыт с интернета |

Оба сервера: пользователь **`smdg`**, путь **`/home/smdg/SMDG`**, один **`VPS_SSH_KEY`**. Публичная строка из лога **Setup SSH** — в `/home/smdg/.ssh/authorized_keys` на **каждом** VPS.

**Важно:** на fileguardian в `authorized_keys` должна быть та же строка, что на primary. Проверка с primary:

```bash
ssh smdg@<VPS_HOST> 'ssh -o BatchMode=yes smdg@74.208.252.225 hostname'
```

Если это работает, а Actions — нет, оставьте `VPS2_SSH_PROXY_JUMP` включённым (по умолчанию в workflow).

После деплоя для **fileguardian** проверяется `https://<domain>/health/ready`.

Перед первым запуском на каждом VPS: Docker, `git clone` в `DEPLOY_PATH`, `secrets/`, `.env`, либо `VPS*_AUTO_CLONE=true`.

### Ошибка `Permission denied (publickey,password)`

В логе Actions шаг **«Setup SSH»** печатает **«Строка для authorized_keys»** — добавьте её на **оба** сервера:

```bash
# на каждом VPS, пользователь smdg:
mkdir -p ~/.ssh && chmod 700 ~/.ssh
# вставьте одну строку из лога workflow
nano ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

Проверка с ПК:

```bash
ssh -i <deploy_key> -o BatchMode=yes smdg@<VPS_HOST> hostname
ssh -i <deploy_key> -o BatchMode=yes smdg@74.208.252.225 hostname
```

Локально публичный ключ из приватного:

```bash
./scripts/show-deploy-ssh-pubkey.sh /path/to/deploy_key
```

В GitHub: **`VPS2_USER`** = `smdg`, **`VPS2_HOST`** = `74.208.252.225`, **`VPS2_DEPLOY_PATH`** можно не задавать (default `/home/smdg/SMDG`).

## Rolling / registry ([`workflows/deploy-rolling.yml`](workflows/deploy-rolling.yml))

Один prod-сервер (`DEPLOY_HOST`, `DEPLOY_DOMAIN`). Для второго VPS rolling нужен отдельный workflow или дублирование job — см. комментарий в начале `deploy-rolling.yml`.
