# FAQ

Frequently asked questions about SMDG.

## General

### What is SMDG?

Secure Medical Data Gateway — a platform for secure medical file exchange with age encryption, time-limited links and a DICOM Viewer.

### Is internet required?

For self-hosted instances, internet is only needed for TLS, updates and external webhooks. Data is processed on your server.

### Is there a demo?

Yes: **https://fileguardian.info** (`demo` profile, data reset every 24 h).

## Security

### How are files encrypted?

**age** (X25519). The key lives in `keys/age.key` (Docker secret in prod).

### Is 2FA supported?

Yes, TOTP (Google Authenticator, Authy). May be mandatory in the `russia` profile.

### Where is audit stored?

`audit_logs/` — daily JSON + CSV. Admin export: Excel/PDF/CSV.

## Files and links

### What is the maximum file size?

Default 600 MB (`MAX_UPLOAD_SIZE_MB`). Smaller in demo.

### Can I revoke a link?

Yes, the owner or admin can revoke it early.

## DICOM

### Do I need a client-side DICOM viewer?

No, server-side render → PNG in the browser.

### Is multi-frame CT supported?

Yes, **Cine** mode for frame sequences.

## Deployment

### Which profile for a clinic in Russia?

`DEPLOYMENT_TYPE=russia` — local storage, FZ-152-oriented settings.

### Can I use S3?

Yes, `intl` and `saas` profiles, or `S3_ENABLED=true` in `.env`.

## Documentation

### Where is Swagger?

`/docs` on your instance.

### Where are user guides?

`/help/` — MkDocs site (after `mkdocs build`).
