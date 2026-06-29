# Security

SMDG security policy.

## Report a vulnerability

Email **security@smdg.example**. Do not open public issues for undisclosed vulnerabilities.

Include:

- issue description;
- reproduction steps;
- SMDG version (`GET /health`);
- preferred disclosure timeline.

## Supported versions

| Version | Supported |
|---------|-----------|
| 4.x | Yes |
| 3.x | Security fixes only |
| < 3.0 | No |

## Cryptography

| Component | Technology |
|-----------|------------|
| Files | age (X25519) |
| Passwords | Argon2id |
| JWT | HS256 |
| 2FA | TOTP (RFC 6238) |
| TLS | Nginx, TLS 1.2+ |

## Secrets

- Docker Secrets in production (`secrets/`).
- `.env` is not committed to git.
- External secret manager recommended (Vault, AWS SM).

## Hardening checklist

- [ ] `DEV_MODE=false`
- [ ] Unique `JWT_SECRET_KEY` (≥64 bytes)
- [ ] PostgreSQL with dedicated role
- [ ] Redis password, internal network only
- [ ] Rate limiting enabled
- [ ] Audit shipped off-host
- [ ] Regular backups of `encrypted/` and DB
- [ ] age key rotation (`python -m app.cli rotate-keys`)

## Audit

All state-changing operations are appended to `audit_logs/`. Entries in English with `user_id`, `tenant_id`, `action`, `resource_id`.

See [src/SECURITY.md](../src/SECURITY.md), [locales/ru/SECURITY.md](../locales/ru/SECURITY.md).

## Compliance

FZ-152 / GDPR template: [src/COMPLIANCE_TEMPLATE.md](../src/COMPLIANCE_TEMPLATE.md).
