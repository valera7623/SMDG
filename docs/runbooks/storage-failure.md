# Runbook: S3/MinIO Storage Failure

## Target
- RTO: 1 hour
- RPO: 15 minutes

## Symptoms
- Upload/download failures
- S3 API errors in logs
- MinIO health endpoint unavailable

## Diagnosis
```bash
docker compose ps minio
docker compose logs minio --tail=100
curl -f http://localhost:9000/minio/health/live
```

## Recovery
```bash
docker compose restart minio
sleep 10
aws s3 sync /backups/smdg/encrypted/ s3://smdg-encrypted/ --delete
python scripts/verify_file_integrity.py --bucket smdg-encrypted
python scripts/sync_storage_metadata.py
```

## Escalation
- If service is not stable in 60 minutes, switch to alternate object storage endpoint.
