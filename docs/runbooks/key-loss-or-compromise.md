# Runbook: Encryption Key Loss or Compromise

## If key material was versioned or exposed in a clone
If a private `age` key was ever present in the repository or a public fork, **treat it as compromised**: generate a new keypair, re-encrypt or rotate data per your policy, and **revoke** the old identity everywhere backups and clients reference it. Prefer keeping `keys/age.key` and `keys/age.pub` only on the host (or in sealed secrets) — never in git.

**Alertmanager → SMDG webhook URL** used a static `x_alert_secret` in the tree in the past: set a new `SMDG_ALERT_WEBHOOK_SECRET` in the app, then replace the placeholder in `alertmanager/alertmanager.yml` at deploy (e.g. `envsubst`) so the query string never contains a live secret in git. **Git history** may still contain old values until you rewrite it (e.g. `git filter-repo`); plan key and webhook rotation accordingly.

## Target
- RTO: 2 hours
- RPO: 0

## Symptoms
- Decryption fails unexpectedly
- Suspicious audit activity around key usage
- Possible secret leak

## Immediate Actions
```bash
docker compose stop smdg
```

## Recovery
```bash
cp /secure/backup/age.key ./keys/age.key
chmod 600 ./keys/age.key
age --decrypt --identity ./keys/age.key ./encrypted/test.age > /dev/null
```

## Compromise Response
```bash
age-keygen -o ./keys/age.key.new
docker compose run --rm smdg python -m app.cli rotate-keys --new-key ./keys/age.key.new --backup-dir /secure/compromised_keys
```

## Audit and Notification
```bash
python scripts/audit_compromised_keys.py --hours 24
```

Notify Security Specialist and record incident timeline.
