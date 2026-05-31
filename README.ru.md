[English](README.md) | **Русский** | [Deutsch](README.de.md) | [Français](README.fr.md)

# SMDG — Secure Medical Data Gateway

**Self-hosted сервис для обмена медицинскими файлами со сквозным шифрованием.**

Версия: **4.0.0** (ядро и DICOM Viewer) · экспорт аудита: **3.1.0**.

SMDG позволяет врачам, клиникам и пациентам безопасно обмениваться
медицинскими файлами. Каждый файл шифруется на сервере с помощью
[age](https://age-encryption.org/), защищается временной одноразовой
ссылкой и полностью логируется в аудите. Встроенный
DICOM Viewer рендерит исследования в браузере, не отдавая клиенту
расшифрованные данные.

## Документация

Полная документация для пользователей и операторов лежит в
[`docs/`](docs/README.md). Источник правды — английская версия в
[`docs/src/`](docs/src/), переводы — в
[`docs/locales/{ru,de,fr}/`](docs/locales/).

- Обзор — [`docs/locales/ru/README.md`](docs/locales/ru/README.md)
- API-руководство — [`docs/locales/ru/API_GUIDE.md`](docs/locales/ru/API_GUIDE.md)
- Архитектура — [`docs/locales/ru/ARCHITECTURE.md`](docs/locales/ru/ARCHITECTURE.md)
- Типы развёртывания — [`docs/locales/ru/DEPLOYMENT.md`](docs/locales/ru/DEPLOYMENT.md)
- Runbook горизонтального масштабирования — [`docs/locales/ru/DEPLOYMENT.md`](docs/locales/ru/DEPLOYMENT.md#горизонтальное-масштабирование-stateless-кластер)
- Runbook возврата к базовому состоянию — [`docs/runbooks/rollback-to-baseline.md`](docs/runbooks/rollback-to-baseline.md)
- DICOM Viewer — [`docs/locales/ru/DICOM_VIEWER.md`](docs/locales/ru/DICOM_VIEWER.md)
- Безопасность — [`docs/locales/ru/SECURITY.md`](docs/locales/ru/SECURITY.md)

## Быстрый старт

```bash
git clone <ваш-репозиторий>
cd smdg
cp .env.example .env
docker compose up --build
```

Откройте <https://localhost>. Учётка по умолчанию в dev: `admin` / `admin`
(немедленно смените).

## Типы развёртывания

Переменная окружения `DEPLOYMENT_TYPE` задаёт матрицу фич:

| Профиль  | Кратко                                                                  |
|----------|-------------------------------------------------------------------------|
| `russia` | ФЗ-152: локальное хранилище, обязательная 2FA, аудит 3 года             |
| `intl`   | S3/MinIO, DICOM, GDPR/HIPAA                                             |
| `single` | Один tenant, упрощённая админка, локальный диск по умолчанию            |
| `saas`   | Multi-tenant, биллинг/white-label, объектное хранилище                  |
| `demo`   | Публичное демо: локальное хранилище, 2FA опционально, лимит загрузки, сброс данных раз в 24 ч |

Подробнее: [`docs/locales/ru/DEPLOYMENT.md`](docs/locales/ru/DEPLOYMENT.md).

**CI/CD (GitHub → VPS):** push в `main` запускает [`.github/workflows/deploy.yml`](.github/workflows/deploy.yml) (SSH + `docker compose`). Задайте секреты `VPS_HOST`, `VPS_USER`, `VPS_SSH_KEY` и при необходимости переменную репозитория `VPS_DEPLOY_PATH`; см. [`.github/DEPLOYMENT_SECRETS.md`](.github/DEPLOYMENT_SECRETS.md). Rolling-деплой с образом из registry — [`.github/workflows/deploy-rolling.yml`](.github/workflows/deploy-rolling.yml).

Для stateless-горизонтального масштабирования (Redis для сессий/кэша/очереди,
Nginx как load balancer, проверки `/health/live` и `/health/ready`, скрипты
blue/green cutover) используйте раздел **«Горизонтальное масштабирование
(stateless-кластер)»** в deployment-гайде.
Процедура возврата в базовое состояние описана в
[`docs/runbooks/rollback-to-baseline.md`](docs/runbooks/rollback-to-baseline.md).

## Мультиязычность

- Веб-UI: English / Русский / Deutsch / Français с переключателем языка
  (см. [`static/js/i18n.js`](static/js/i18n.js)).
- API-документация: `/docs` (English), `/docs/ru`, `/docs/de`, `/docs/fr`
  и `/openapi.{ru,de,fr}.json`.
- Документация: `docs/src/` (английский) + `docs/locales/<lang>/`.

## Security Scanning

CI workflow [`security-scan.yml`](.github/workflows/security-scan.yml) запускает
SAST, SCA, secrets, container и DAST проверки для `push`, `pull_request`,
`schedule` и ручного запуска.

### Автопереключение режимов (`SECURITY_SCAN_MODE`)

Workflow автоматически выбирает режим по событию:

- `schedule` -> `audit`
- `push` / `pull_request` / `workflow_dispatch` -> `balanced` (по умолчанию)
- для несcheduled-событий можно переопределить через repository variable
  `SECURITY_SCAN_MODE=strict` (или `balanced`)

Фактическое выражение в workflow:

```yaml
env:
  SECURITY_SCAN_MODE: ${{ github.event_name == 'schedule' && 'audit' || (vars.SECURITY_SCAN_MODE == 'strict' && 'strict' || 'balanced') }}
```

Как настроить repository variable в GitHub:

1. Откройте репозиторий -> **Settings** -> **Secrets and variables** -> **Actions**.
2. Перейдите на вкладку **Variables**.
3. Нажмите **New repository variable**.
4. Укажите:
   - Name: `SECURITY_SCAN_MODE`
   - Value: `strict` (или `balanced`)

Пример через GitHub CLI:

```bash
gh variable set SECURITY_SCAN_MODE --body strict
```

## Changelog (Load Testing)

- Добавлен baseline для auth capacity в [`docs/load-testing.md`](docs/load-testing.md),
  раздел **"Known baseline (single instance)"**.
- Текущий измеренный baseline для одного инстанса SMDG:
  - safe: `AUTH_RPS=3` (`error_rate=0`, `503_count=0`)
  - warning: `AUTH_RPS=4` (начинается деградация)
  - overload: `AUTH_RPS>=5` (устойчивый рост `503`)

## Лицензия

MIT. Автор: Валерий Попов.
