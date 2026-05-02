# Security Policy

> **Translation status:** English stub. The authoritative Russian
> document is [`docs/locales/ru/SECURITY.md`](../locales/ru/SECURITY.md).

## Reporting a vulnerability

Please report security issues privately to **security@smdg.example**.
Do **not** file a public GitHub issue for undisclosed vulnerabilities.
We aim to acknowledge reports within 48 hours and publish a fix within
30 days, depending on severity.

Include in your report:

- A short description of the issue.
- Reproduction steps or proof-of-concept.
- The affected SMDG version (`GET /health`).
- Your preferred contact / disclosure timeline.

## Supported versions

| Version | Supported |
|---------|-----------|
| 4.x     | Yes       |
| 3.x     | Security fixes only |
| < 3.0   | No        |

## Dependency vulnerability decisions

Authoritative detail (Russian): [`docs/locales/ru/SECURITY.md`](../locales/ru/SECURITY.md)
section **11.5.6** — minimum **Pillow** version (CVE-2026-25990, CVE-2026-40192)
and **ecdsa** / CVE-2024-23342 risk acceptance while no fixed PyPI release exists.

## Cryptography

- File encryption: `age` (X25519) envelope encryption.
- Passwords: Argon2id (`argon2-cffi`).
- JWT: HS256 signed with `JWT_SECRET_KEY` (rotate regularly).
- 2FA: TOTP (RFC 6238) with 30 s window and 6-digit codes.
- TLS: terminated by Nginx with modern cipher suites.

## Secrets management

Secrets are mounted from the `secrets/` directory via Docker Secrets.
Never commit secrets to Git; `.env` files are ignored. In production,
use an external secret manager (Vault, AWS Secrets Manager, etc.).

## Hardening checklist

- `DEV_MODE=false` in production.
- Unique, long `JWT_SECRET_KEY` (≥ 64 bytes).
- PostgreSQL with a dedicated role, non-default password.
- Redis password-protected and bound to an internal network.
- Rate limiting enabled (default is on).
- Audit logs shipped off-host (rsyslog, Loki, etc.).
- Regular backups of `encrypted/` and the database.
- Regular age key rotation (`python -m app.cli rotate-keys`).

## Audit logging

Every state-changing operation is appended to `audit_logs/`. Log
entries are written in English and include user id, tenant id, action,
resource id and a SHA-256 of the payload where appropriate. Clients
are expected to localise audit messages for display.
