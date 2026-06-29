# SMDG — документация (MkDocs)

Полная документация **Secure Medical Data Gateway** — платформы для безопасного обмена медицинскими файлами с end-to-end шифрованием, DICOM Viewer и мультитенантностью.

## Быстрый старт

```bash
poetry install --with docs
poetry run mkdocs serve
```

Откройте http://127.0.0.1:8000

## Сборка сайта

```bash
poetry run mkdocs build
# Результат: site/
```

## Структура

| Раздел | Аудитория | Описание |
|--------|-----------|----------|
| [user-guide/](user-guide/) | Врачи, операторы | Загрузка файлов, ссылки, DICOM |
| [admin-guide/](admin-guide/) | DevOps, админы | Деплой, конфигурация, бэкапы |
| [developer-guide/](developer-guide/) | Разработчики | Архитектура, мультитенантность, тесты |
| [api/](api/) | Интеграторы | REST API с примерами |
| [deployment/](deployment/) | DevOps | Docker, VPS, CI/CD |
| [misc/](misc/) | Все | Changelog, FAQ, глоссарий, безопасность |

## Дополнительная документация

Помимо MkDocs-сайта в репозитории есть:

| Каталог | Назначение |
|---------|------------|
| [src/](src/) | Английский source-of-truth (legacy markdown) |
| [locales/](locales/) | Переводы ru / de / fr (sync через `generate_i18n.py`) |
| [runbooks/](runbooks/) | Операционные runbook'и для on-call |

## Языки / Languages

| Язык | URL |
|------|-----|
| Русский (по умолчанию) | `/help/` |
| English | `/help/en/` |

Переключатель языка — в шапке сайта (Material). При первом визите язык определяется автоматически по настройкам браузера.

## Интерактивная API-документация

| URL | Описание |
|-----|----------|
| `/docs` | Swagger UI (OpenAPI) |
| `/help/` | Руководства пользователя, админа, разработчика (MkDocs) |

На проде (demo): `https://fileguardian.info/help/`
