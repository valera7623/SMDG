<!-- smdg-i18n-header-start
source: docs/src/CHANGELOG.md
source_sha1: 6f148bebc20423b8db6fe49ef992df783e73d09e
language: fr
last_sync: 2026-05-31
status: translated
smdg-i18n-header-end -->

# Journal des modifications

> **Statut de traduction :** traduction française. La version russe faisant
> autorité du journal des modifications se trouve dans
> [`docs/locales/ru/CHANGELOG.md`](../ru/CHANGELOG.md).

Toutes les modifications notables de ce projet sont documentées dans ce
fichier. Le format est basé sur [Keep a Changelog](https://keepachangelog.com/)
et le projet suit le [versionnage sémantique](https://semver.org/).

## [Non publié]

- Nouveau profil de déploiement `demo` (`DEPLOYMENT_TYPE=demo`) : stockage
  local uniquement, 2FA facultative, petite limite de téléversement, point de
  terminaison public `GET /api/demo/info` et réinitialisation automatique des
  données toutes les 24 heures.
- Limitation de débit à l'inscription (`RATE_LIMIT_REGISTER`, `10/minute` par
  défaut, `3/hour` en mode démo) sur `POST /api/auth/register`.
- Arborescence d'audit des accès aux fichiers dans le panneau d'administration,
  alimentée par `GET /api/admin/file-audit/`.
- Transitions de page fluides dans toute l'interface web.

## [4.0.0] — 2026-04

- Internationalisation complète (i18n) de l'interface web : anglais / russe /
  allemand / français avec un sélecteur de langue à l'exécution.
- Points de terminaison OpenAPI localisés : `/openapi.ru.json`,
  `/openapi.de.json`, `/openapi.fr.json`.
- Documentation restructurée en `docs/src/` (source) et
  `docs/locales/<lang>/` (traductions).

## [3.1.0]

- Export d'audit administrateur aux formats Excel, PDF et CSV avec filtres par
  date/utilisateur.

## [3.0.0]

- Visionneuse DICOM avec multi-frame, préréglages Window/Level et mesures.
- Points de terminaison DICOMweb (QIDO-RS, WADO-RS).
- Intégration de visionneuse de style OHIF.

## [2.1.0]

- Webhooks avec signatures HMAC-SHA256 et nouvelles tentatives à backoff
  exponentiel.

## [2.0.0]

- Abstraction StorageBackend (Local / S3 avec règles de cycle de vie).
- Script de migration FS → S3.

## [1.0.0]

- Version initiale : téléversement/téléchargement avec chiffrement age,
  JWT + 2FA, panneau d'administration, journaux d'audit.
