# Getting started

Guide for doctors, operators and SMDG end users.

## Why SMDG

SMDG helps you:

- securely exchange medical files between doctors, clinics and patients;
- encrypt data on the server (age) and share via time-limited links;
- view DICOM studies in the browser;
- maintain a full audit trail of all operations.

## First login

1. Open your instance URL, e.g. `https://fileguardian.info`
2. Enter your **username** and **password**.
3. If 2FA is enabled, enter the code from your authenticator app.
4. Click **Sign in**.

!!! tip "Public demo"
    https://fileguardian.info runs the `demo` profile: data is reset every 24 hours. Do not upload real personal data.

## Registration

If registration is enabled by the administrator:

1. On the login page click **Register**.
2. Fill in email, password and select a role.
3. Click **Create account**.

### Roles

| Role | Permissions |
|------|-------------|
| **user** | Upload and download own files |
| **doctor** | Extended file access within the tenant |
| **admin** | User management, audit, export |
| **super_admin** | Cross-tenant operations (`saas` profile) |

## Main menu

After login:

| Item | Purpose |
|------|---------|
| **Files** | Uploaded files list, new uploads |
| **DICOM** | Medical imaging viewer |
| **Admin** | `admin` / `super_admin` only |

## Two-factor authentication (2FA)

In security settings:

1. Click **Set up 2FA**.
2. Scan the QR code in Google Authenticator / Authy.
3. Enter the 6-digit code to confirm.

!!! warning "`russia` profile"
    In the `russia` profile, 2FA may be mandatory per organisational policy.

## Change password

**Profile → Security → Change password**

Minimum requirements are set by the administrator (default: at least 8 characters).

## UI language

The web UI supports **English**, **Russian**, **German** and **French**. Use the switcher in the header.

## Next steps

- [Upload and manage files](files.md)
- [Create sharing links](links-and-sharing.md)
- [View DICOM](dicom.md)
