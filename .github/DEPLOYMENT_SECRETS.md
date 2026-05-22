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

### Парольный SSH между VPS ≠ деплой из GitHub Actions

Если **smdg@VPS1 → VPS2 по паролю** работает, это **не значит**, что Actions войдёт по ключу. Workflow использует только **`VPS_SSH_KEY`** (publickey, `BatchMode=yes`, пароль не спрашивается).

На **каждом** VPS для пользователя **`smdg`** один раз добавьте публичный ключ деплоя (строка из лога Actions «Setup SSH» или `./scripts/show-deploy-ssh-pubkey.sh`):

```bash
# зайдите на сервер по паролю (или с консоли хостинга)
mkdir -p ~/.ssh && chmod 700 ~/.ssh
nano ~/.ssh/authorized_keys   # одна строка ssh-ed25519 ... или ssh-rsa ...
chmod 600 ~/.ssh/authorized_keys
```

С вашего ПК (после этого Actions тоже сможет):

```bash
ssh-copy-id -i ./deploy_key.pub smdg@<VPS_HOST>
ssh-copy-id -i ./deploy_key.pub smdg@74.208.252.225
```

`ProxyJump` (fileguardian через primary) всё равно проверяет **тот же публичный ключ** на конечном хосте; пароль между VPS для CI не используется.

**Важно:** на fileguardian в `authorized_keys` должна быть та же строка, что на primary. Проверка с primary (после добавления ключа):

```bash
ssh smdg@<VPS_HOST> 'ssh -o BatchMode=yes smdg@74.208.252.225 hostname'
```

Если это работает, а Actions — нет, оставьте `VPS2_SSH_PROXY_JUMP` включённым (по умолчанию в workflow).

После деплоя для **fileguardian** проверяется `https://<domain>/health/ready` (до 40×6 с). **502** обычно значит: контейнер `smdg` ещё стартует (миграции, ключи, MinIO) или упал — смотрите `docker compose logs smdg` на VPS. Отключить проверку: Variable `VPS2_SKIP_SMOKE_TEST=true`.

Перед первым запуском на каждом VPS: Docker, `git clone` в `DEPLOY_PATH`, `secrets/`, `.env`, либо `VPS*_AUTO_CLONE=true`.

### `password authentication failed for user "smdg_user"` (alembic / 502)

Том **`pgdata`** хранит пароль Postgres **с первого** `docker compose up`. Файл **`secrets/postgres_password.txt`** меняется отдельно — если они разошлись, `smdg` не подключится к `db`.

**Вариант A** — выровнять пароль в БД под текущий secret (данные сохраняются):

```bash
cd /home/smdg/SMDG
./scripts/fix-postgres-password-mismatch.sh
docker compose up -d smdg
```

**Вариант B** — вернуть в `secrets/postgres_password.txt` **старый** пароль (тот, с которым поднимали БД впервые).

**Вариант C** — новый пароль и пустая БД (удалит данные):

```bash
docker compose down
docker volume rm smdg_pgdata   # имя: docker volume ls | grep pgdata
# затем снова up с актуальным secrets/postgres_password.txt
```

На **втором VPS** не копируйте `pgdata` с первого — только свой `secrets/postgres_password.txt` и свой том.

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
