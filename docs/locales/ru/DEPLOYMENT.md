<!-- smdg-i18n-header-start
source: docs/src/DEPLOYMENT.md
source_sha1: b23f0469215797d128b33765288f7ea12ec45b97
language: ru
last_sync: 2026-04-20
status: needs-translation
smdg-i18n-header-end -->

# Типы развёртывания SMDG

Переменная окружения **`DEPLOYMENT_TYPE`**: `russia` | `intl` | `single` | `saas`.

## Russia (`russia`)

- Локальное хранилище (`S3_ENABLED=false`).
- Обязательная 2FA на уровне политики входа.
- Аудит 1095 дней (`AUDIT_3_YEARS` в матрице).
- Криптопрофиль ГОСТ (`GOST_CRYPTO`): сейчас заглушка поверх age — замените перед продакшеном.

```bash
docker build --build-arg DEPLOYMENT_TYPE=russia -t smdg:russia .
docker compose -f docker-compose.yml -f docker-compose.russia.yml up -d
```

## International (`intl`)

- S3 / MinIO, DICOM Viewer, GDPR-ориентированные фичи в матрице.

```bash
DEPLOYMENT_TYPE=intl docker compose up -d
```

Используйте overlay `docker-compose.intl.yml` для лимитов ресурсов.

## Single tenant (`single`)

- Один tenant по умолчанию, упрощённая админка (`SIMPLE_ADMIN`), локальное хранилище по умолчанию.
- При выключенном `MULTI_TENANCY` роль **`super_admin`** не переключает организацию через `Host` или `X-Tenant-*`: контекст всегда tenant с `tenant_default_subdomain` (как у остальных ролей). Это исключает скрытый multi-tenant в single-профиле.

```bash
docker compose -f docker-compose.yml -f docker-compose.single.yml up -d
```

Если в `.env` уже включён S3 с валидными ключами, приложение сохранит совместимость и продолжит использовать S3.

## SaaS (`saas`)

- Multi-tenancy, биллинг и white-label в матрице; требуется рабочий S3 вне dev.

```bash
docker compose -f docker-compose.yml -f docker-compose.saas.yml up -d
```

## Миграция со старой версии

1. Задайте `DEPLOYMENT_TYPE` (для текущего docker-стека с MinIO рекомендуется `intl`).
2. Запустите `python scripts/migrate_deployment_type.py --target <тип>` для чеклиста.
3. Перезапустите сервисы.

Шаблоны `.env`: `.env.<profile>.example` в корне репозитория.
