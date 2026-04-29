# Compliance Template (FZ-152 / GDPR)

> **Translation status:** English stub. The full Russian version is at
> [`docs/locales/ru/COMPLIANCE_TEMPLATE.md`](../locales/ru/COMPLIANCE_TEMPLATE.md).

This document is a _template_ — it is **not** legal advice. Fill it in
together with your data-protection officer and legal counsel before
deploying SMDG in production.

## 1. Operator identification

- Legal name of the operator: `<fill in>`
- Contact for data subjects: `<email>`
- Data Protection Officer (DPO): `<name, email>`
- Applicable regulations:
  - `[ ]` FZ-152 (Russia)
  - `[ ]` GDPR (EU)
  - `[ ]` HIPAA (USA)

## 2. Categories of personal data processed

- `[ ]` Identifiers (name, email, login)
- `[ ]` Authentication data (password hashes, 2FA secrets)
- `[ ]` Medical data (DICOM studies, reports, file metadata)
- `[ ]` Technical data (IP addresses, user agents, audit logs)

## 3. Legal basis for processing

Declare the legal basis for each category (consent, contract, legal
obligation, vital interest, public interest, legitimate interest).

## 4. Data retention

| Data category                 | Retention              |
|-------------------------------|------------------------|
| Encrypted files               | 30 days (configurable) |
| Audit logs                    | 365 or 1095 days       |
| User accounts (active)        | Until deletion request |
| User accounts (deactivated)   | 90 days                |
| Webhook delivery history      | 90 days                |

## 5. Data subject rights

- Right to access: `GET /api/users/me`
- Right to rectification: admin panel `/admin/users`
- Right to erasure: `DELETE /api/users/me` and audit redaction job
- Right to data portability: `GET /api/users/me/export`

## 6. Security measures

- Encryption at rest: `age` (X25519) envelope encryption.
- Encryption in transit: TLS 1.2+ terminated by Nginx.
- Password hashing: Argon2id.
- 2FA: TOTP (RFC 6238).
- Content checks: MIME and extension validation on upload.
- Access control: RBAC with least-privilege defaults.

## 7. Incident response

Document the plan for detection, containment and notification of data
breaches. See [SECURITY.md](SECURITY.md).
