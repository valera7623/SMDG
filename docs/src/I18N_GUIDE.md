# Internationalisation (i18n) Guide

This guide documents how SMDG handles translations across the web UI,
the API documentation and the user documentation.

## Language policy

| Item                              | Language               | Notes                                           |
|-----------------------------------|------------------------|-------------------------------------------------|
| Variable / function names         | English                | No exceptions                                    |
| Code comments                     | English                | No exceptions                                    |
| Docstrings                        | English                | Full sentences                                   |
| Commit messages                   | English                | Conventional Commits                             |
| API descriptions (OpenAPI)        | English                | `/openapi.json` is the source of truth           |
| Audit logs                        | English                | e.g. `User 42 downloaded file 123`               |
| API error messages                | English                | Clients translate on the client side             |
| User documentation                | en / ru / de / fr      | `docs/src/` + `docs/locales/`                    |
| UI strings                        | Runtime i18n           | Detected from browser, persisted in localStorage |

## Directory layout

```
docs/
├── src/                 English source of truth
├── locales/
│   ├── ru/              Russian translations
│   ├── de/              German translations
│   └── fr/              French translations
└── generate_i18n.py     Sync script

static/
├── locales/
│   ├── en.js            UI translations — English (source)
│   ├── ru.js            UI translations — Russian
│   ├── de.js            UI translations — German
│   └── fr.js            UI translations — French
├── js/i18n.js           Runtime (detect, load, render)
└── css/language-selector.css  Dropdown styles

app/main.py              /openapi.ru.json, /openapi.de.json, /openapi.fr.json
                         /docs/ru, /docs/de, /docs/fr
```

## UI translations

### How the runtime works

1. `static/js/i18n.js` is loaded on every HTML page.
2. On `DOMContentLoaded` it calls `I18N.init()`:
   - reads the saved language from `localStorage["smdg_language"]`,
   - falls back to `navigator.languages`,
   - ultimately falls back to `en`.
3. The locale dictionary is loaded as a regular script tag
   (`/static/locales/<lang>.js`) and registers itself on
   `window.SMDG_I18N.translations[<lang>]`.
4. The DOM is walked for the following attributes and updated:

   | Attribute                | Target                                      |
   |--------------------------|---------------------------------------------|
   | `data-i18n`              | `textContent` of the element                |
   | `data-i18n-placeholder`  | `placeholder` attribute (inputs/textareas)  |
   | `data-i18n-value`        | `value` attribute (submit buttons)          |
   | `data-i18n-title`        | `title` attribute, or document title on `<title>` |
   | `data-i18n` on `<title>` | `document.title`                            |

5. A `CustomEvent` named `i18n:updated` is dispatched on `window`
   after each language change.

### Adding a new UI string

1. Add the key to `static/locales/en.js` with the English source text.
2. Add the same key to `ru.js`, `de.js`, `fr.js` with translations.
3. Mark the DOM element:

   ```html
   <button data-i18n="files.upload">Upload</button>
   <input data-i18n-placeholder="auth.password" type="password">
   ```

4. For dynamic content, call `window.I18N.t("your.key")` or
   `window.I18N.t("welcome", { username: name })`.

### Adding a new language

1. Copy `static/locales/en.js` to `static/locales/<lang>.js`.
2. Replace the assignment at the bottom:
   ```js
   global.SMDG_I18N.translations.<lang> = translations;
   ```
3. Translate every value.
4. In `static/js/i18n.js` add `<lang>` to `availableLangs` and
   `langNames`.
5. Run the app and verify the new language in the dropdown.

### Using i18n in new HTML components

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title data-i18n="app.title">SMDG</title>
    <link rel="stylesheet" href="/static/css/style.css">
    <link rel="stylesheet" href="/static/css/language-selector.css">
    <script src="/static/js/i18n.js" defer></script>
</head>
<body>
    <header>
        <h1 data-i18n="app.title">SMDG</h1>
        <!-- #language-selector is injected here automatically -->
    </header>
    <main>
        <button data-i18n="files.upload">Upload file</button>
        <div id="status" data-i18n="common.loading">Loading…</div>
    </main>
</body>
</html>
```

If dynamic content is added after the initial render, call
`window.I18N.updatePageTranslations(container)` on the new root.

## Documentation translations

The English source of truth for user documentation lives under
`docs/src/`. Translations live under `docs/locales/<lang>/`.

### Sync workflow

1. Edit or add a file under `docs/src/`.
2. Run the sync script locally:

   ```bash
   python docs/generate_i18n.py
   ```

3. The script creates a stub in each `docs/locales/<lang>/` directory
   and embeds a header with the SHA-1 of the source:

   ```markdown
   <!-- smdg-i18n-header-start
   source: docs/src/FEATURES.md
   source_sha1: a1b2c3…
   language: ru
   last_sync: 2026-04-20
   status: needs-translation
   smdg-i18n-header-end -->
   ```

4. Translate the stub. Keep the SHA-1 header unchanged.
5. When the English source changes, the script detects the SHA-1
   mismatch and refreshes the header, marking the file stale so
   translators know something needs attention.

### CI enforcement

`.github/workflows/docs-i18n.yml` runs on pull requests with
`--strict --dry-run`. The build fails if any translation is missing
or stale. On pushes to `main` (and on a weekly cron) the workflow
opens a PR with updated stubs via `peter-evans/create-pull-request`.

Run locally before opening a PR:

```bash
python docs/generate_i18n.py --strict --dry-run
```

### Adding a new documentation language

1. Add the locale code to `SUPPORTED_LANGS` in
   `docs/generate_i18n.py`.
2. Run `python docs/generate_i18n.py --langs <lang>` to generate
   the stubs.
3. Translate the stubs and update the documentation index in
   `docs/README.md`.

## Localised OpenAPI

`app/main.py` exposes three translated copies of the OpenAPI document:

- `GET /openapi.ru.json` — Russian metadata.
- `GET /openapi.de.json` — German metadata.
- `GET /openapi.fr.json` — French metadata.

Three Swagger UI shells are available as well:

- `/docs/ru`
- `/docs/de`
- `/docs/fr`

Only the `info.title` and `info.description` fields are translated;
per-endpoint descriptions remain in English per the language policy.
Clients that need localised endpoint summaries should maintain their
own mapping from `operationId` to translated strings.

## Audit logs

Audit messages are always written in English:

- `User 42 uploaded file 123 (2.3 MB) from 10.0.0.5`
- `Admin 1 deleted user 42`
- `Webhook delivery 7 failed after 3 attempts`

Rationale: audit logs are consumed by compliance tooling and SIEM
pipelines where stable English strings make parsing deterministic.
Clients that display audit entries to end users should translate them
based on the structured event type.
