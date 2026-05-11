# Secret Rotation Runbook

Use this runbook when a secret was committed, exposed in scanner reports, or
shared outside the deployment boundary.

## Scope

Rotate every secret that may have been present in tracked files or generated
reports:

- `REDIS_PASSWORD`
- `JWT_SECRET_KEY` or `secrets/jwt_secret.txt`
- `ADMIN_PASSWORD` or `secrets/admin_password.txt`
- `SMDG_ALERT_WEBHOOK_SECRET`
- PostgreSQL password in `secrets/postgres_password.txt`
- Age private key in `secrets/age.key`, if scanner output or git history
  indicates it was exposed

## Steps

1. Generate new values on a trusted host. Do not paste live secrets into git,
   issue trackers, chat, or CI logs.
2. Update the deployment secret store or files under `secrets/`.
3. Restart services that consume the rotated values.
4. Invalidate old sessions when rotating JWT secrets. Users will need to log in
   again.
5. For Redis and PostgreSQL, update the server-side password first, then update
   application secrets and restart the application.
6. For Alertmanager, update `SMDG_ALERT_WEBHOOK_SECRET` in SMDG and replace the
   deployed Alertmanager webhook URL placeholder with the new value.
7. If the age private key was exposed, re-encrypt stored files with a new key
   pair or treat previously encrypted payloads as compromised.
8. Run gitleaks and security scans again. Store reports outside git.

## Git Cleanup

Generated files such as `.env.prod`, `reports/*`, and `load-test-results/*`
must stay untracked. If any of them were pushed to a remote, rotate the affected
secrets and consider repository history cleanup with a tool such as
`git filter-repo`.
