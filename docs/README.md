# SMDG Documentation

**[English](src/README.md)** | [Русский](locales/ru/README.md) | [Deutsch](locales/de/README.md) | [Français](locales/fr/README.md)

This directory contains the SMDG user- and operator-facing documentation.

## MkDocs site (MedInsight-style)

Интерактивный сайт документации на **MkDocs Material** с i18n (RU + EN):

```bash
poetry install --with docs
poetry run mkdocs serve    # http://127.0.0.1:8000
poetry run mkdocs build    # → site/
```

| Раздел | Аудитория |
|--------|-----------|
| [user-guide/](user-guide/) | Пользователи |
| [admin-guide/](admin-guide/) | Администраторы |
| [developer-guide/](developer-guide/) | Разработчики |
| [api/](api/) | Интеграторы |
| [deployment/](deployment/) | DevOps |
| [misc/](misc/) | Changelog, FAQ |

Подробнее: [MKDOCS.md](MKDOCS.md). Конфигурация: [`mkdocs.yml`](../mkdocs.yml) в корне репозитория.

На проде (demo): `https://fileguardian.info/help/`

## Structure (legacy i18n markdown)

```
docs/
├── src/               English — source of truth
├── locales/
│   ├── ru/            Russian
│   ├── de/            German
│   └── fr/            French
├── generate_i18n.py   translation sync script
└── README.md          this file
```

## Workflow

1. Edit the English source under `docs/src/`.
2. Run `python docs/generate_i18n.py` to refresh stubs in
   `docs/locales/<lang>/` for any new or updated page.
3. Translate the generated stubs and commit.

The sync script is executed automatically in CI (see
[`.github/workflows/docs-i18n.yml`](../.github/workflows/docs-i18n.yml))
and will fail the build in `--strict` mode when translations are
missing or stale.

## Available pages

| Page                      | English (source)                                         |
|---------------------------|----------------------------------------------------------|
| Archive E2E runbook       | [ARCHIVE_E2E.md](ARCHIVE_E2E.md)                         |
| Overview                  | [src/README.md](src/README.md)                           |
| API guide                 | [src/API_GUIDE.md](src/API_GUIDE.md)                     |
| Architecture              | [src/ARCHITECTURE.md](src/ARCHITECTURE.md)               |
| Changelog                 | [src/CHANGELOG.md](src/CHANGELOG.md)                     |
| Compliance template       | [src/COMPLIANCE_TEMPLATE.md](src/COMPLIANCE_TEMPLATE.md) |
| Contributing              | [src/CONTRIBUTING.md](src/CONTRIBUTING.md)               |
| Deployment profiles       | [src/DEPLOYMENT.md](src/DEPLOYMENT.md)                   |
| DICOM Viewer              | [src/DICOM_VIEWER.md](src/DICOM_VIEWER.md)               |
| Feature matrix            | [src/FEATURES.md](src/FEATURES.md)                       |
| i18n guide                | [src/I18N_GUIDE.md](src/I18N_GUIDE.md)                   |
| Multi-tenancy             | [src/MULTI_TENANCY.md](src/MULTI_TENANCY.md)             |
| Security policy           | [src/SECURITY.md](src/SECURITY.md)                       |
| Testing strategy          | [src/TESTING.md](src/TESTING.md)                         |
| Troubleshooting           | [src/TROUBLESHOOTING.md](src/TROUBLESHOOTING.md)         |
