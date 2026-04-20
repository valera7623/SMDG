[English](README.md) | **Русский** | [Deutsch](README.de.md) | [Français](README.fr.md)

# SMDG — Secure Medical Data Gateway

**Self-hosted сервис для обмена медицинскими файлами со сквозным шифрованием.**

Версия: **4.0.0** (ядро и DICOM Viewer) · экспорт аудита: **3.1.0**.

SMDG позволяет врачам, клиникам и пациентам безопасно обмениваться
медицинскими файлами. Каждый файл шифруется на сервере с помощью
[age](https://age-encryption.org/), защищается временной одноразовой
ссылкой, проверяется ClamAV и полностью логируется в аудите. Встроенный
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

Подробнее: [`docs/locales/ru/DEPLOYMENT.md`](docs/locales/ru/DEPLOYMENT.md).

## Мультиязычность

- Веб-UI: English / Русский / Deutsch / Français с переключателем языка
  (см. [`static/js/i18n.js`](static/js/i18n.js)).
- API-документация: `/docs` (English), `/docs/ru`, `/docs/de`, `/docs/fr`
  и `/openapi.{ru,de,fr}.json`.
- Документация: `docs/src/` (английский) + `docs/locales/<lang>/`.

## Лицензия

MIT. Автор: Валерий Попов.
