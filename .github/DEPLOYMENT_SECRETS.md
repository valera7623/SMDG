# GitHub Actions: секреты для деплоя на VPS

Два независимых workflow запускаются параллельно при push в `main`.

| Workflow | Сервер | Compose-файл |
|----------|--------|--------------|
| [`deploy-primary.yml`](workflows/deploy-primary.yml) | primary — 186.246.3.65 | `docker-compose.yml` (полный стек) |
| [`deploy-fileguardian.yml`](workflows/deploy-fileguardian.yml) | fileguardian — 74.208.252.225 | `docker-compose.demo.yml` (demo) |

---

## Общий SSH-ключ

| Secret | Описание |
|--------|----------|
| `VPS_SSH_KEY` | Приватный ключ (весь файл от `-----BEGIN` до `-----END`). Один на **оба** VPS. |

Публичная строка (из лога Actions шаг **Setup SSH**) — в `/home/smdg/.ssh/authorized_keys` на **обоих** серверах.

```bash
# на каждом VPS под пользователем smdg:
mkdir -p ~/.ssh && chmod 700 ~/.ssh
echo "ssh-ed25519 AAAA... строка из лога" >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

---

## Сервер 1: primary (186.246.3.65) — `deploy-primary.yml`

### Required Secrets

| Name | Значение |
|------|----------|
| `VPS_HOST` | `186.246.3.65` |
| `VPS_USER` | `smdg` |

### Optional Variables

| Name | Default |
|------|---------|
| `VPS_DEPLOY_PATH` | `/home/smdg/SMDG` |
| `VPS_AUTO_CLONE` | `true` — git clone при первом запуске |

На VPS нужен каталог `secrets/` с файлами (Docker secrets):

```
secrets/jwt_secret.txt       (≥48 символов)
secrets/admin_password.txt
secrets/postgres_password.txt
secrets/age.key
```

---

## Сервер 2: fileguardian (74.208.252.225) — `deploy-fileguardian.yml`

### Required Secrets

| Name | Значение |
|------|----------|
| `VPS2_HOST` | `74.208.252.225` |
| `VPS2_USER` | `smdg` |
| `VPS2_SSH_KEY` | Приватный SSH-ключ для fileguardian (можно использовать общий `VPS_SSH_KEY`) |

### Optional Secrets

| Name | Описание |
|------|----------|
| `VPS_GITHUB_TOKEN` | PAT для git clone, если включён `VPS2_AUTO_CLONE` и репозиторий приватный |

### Optional Variables

| Name | Default | Описание |
|------|---------|----------|
| `VPS2_DEPLOY_PATH` | `/home/smdg/SMDG` | путь к clone |
| `VPS2_AUTO_CLONE` | — | `true`: git clone при первом запуске |
| `VPS2_SSH_PROXY_JUMP` | включён | `false` — прямой SSH (если порт 22 открыт с интернета) |
| `VPS2_DOMAIN` | `fileguardian.info` | домен для smoke-теста |
| `VPS2_SKIP_SMOKE_TEST` | — | `true` — пропустить проверку `/health/ready` |

На VPS нужен **`.env`** (не в git, Docker secrets не нужны в demo-режиме):

```bash
cd /home/smdg/SMDG
cp .env.demo.example .env
nano .env
# обязательно задать:
#   DOMAIN=fileguardian.info
#   LETSENCRYPT_EMAIL=you@email.com
#   JWT_SECRET_KEY=<64 hex символа, ≥48>
#   POSTGRES_PASSWORD=<ваш пароль — тот же, с которым создавался pgdata>
#   ADMIN_PASSWORD=Demo1234!
```

---

## Частые ошибки

### `Permission denied (publickey,password)` — SSH

Публичный ключ не добавлен в `authorized_keys`. Строка — в логе Actions, шаг **Setup SSH**.

Проверка с ПК:

```bash
ssh -i ./deploy_key -o BatchMode=yes smdg@186.246.3.65 hostname
ssh -i ./deploy_key -o BatchMode=yes smdg@74.208.252.225 hostname
```

По умолчанию fileguardian подключается через **ProxyJump** (primary). Если primary проходит, а fileguardian нет — добавьте ключ на fileguardian.

### `password authentication failed for user "smdg_user"` — PostgreSQL / 502

Пароль в `.env` или `secrets/postgres_password.txt` не совпадает с томом `pgdata`.

```bash
cd /home/smdg/SMDG
./scripts/fix-postgres-password-mismatch.sh
docker compose up -d smdg   # или docker compose -f docker-compose.demo.yml up -d smdg
```

### 502 Bad Gateway после деплоя

Nginx отвечает, но `smdg:8000` ещё не готов (миграции, `init_keys`, S3). Smoke test ждёт до 4 минут. Смотрите лог:

```bash
docker compose logs smdg --tail 80         # primary
docker compose -f docker-compose.demo.yml logs smdg --tail 80   # fileguardian
```

---

## Rolling / zero-downtime

Отдельный workflow: [`deploy-rolling.yml`](workflows/deploy-rolling.yml) — Docker Hub, zero-downtime, `DEPLOY_HOST`.
