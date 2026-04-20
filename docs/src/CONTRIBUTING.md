# Contributing

SMDG is currently developed privately by a single author.

External pull requests are not accepted at this time. If you have a question
or a proposal, please open an Issue in the repository.

## Language policy

- Source code, comments, docstrings, commit messages and API descriptions are
  written in English.
- User-facing documentation lives under `docs/src/` (English — source of truth)
  and is translated into `docs/locales/{ru,de,fr}/` via the sync script
  `docs/generate_i18n.py`.
- UI strings are defined in `static/locales/<lang>.js` and applied through
  the runtime in `static/js/i18n.js`.

## Adding a new translation

1. Run `python docs/generate_i18n.py` to create stub files in
   `docs/locales/<lang>/` for any new or updated English source.
2. Translate the generated stub. Keep headings, file paths, and code blocks
   identical to the English source.
3. Open an Issue to request review.

## Reporting issues

Open an Issue with:

- SMDG version (`/health` endpoint output or `git rev-parse HEAD`)
- Deployment profile (`DEPLOYMENT_TYPE`)
- Logs with sensitive data redacted
- Steps to reproduce
