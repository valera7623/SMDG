# Runbook: Encryption Key Loss or Compromise

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
