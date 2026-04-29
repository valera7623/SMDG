"""Archive service for moving old data to cold storage."""

from __future__ import annotations

import asyncio
import gzip
import hashlib
import logging
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import aiofiles
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import func, select

from app.core import PRIVATE_KEY_PATH, encrypted_storage, get_public_key
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.metrics import archived_total, archive_failures_total, restore_duration_seconds
from app.crypto.crypto import crypto_manager
from app.models.archive import ArchiveRecord, ArchiveRestoreRequest
from app.models.deleted_user import DeletedUser
from app.models.file import File

logger = logging.getLogger(__name__)


class ColdStorageBackend:
    """Cold storage backend supporting filesystem and S3-compatible APIs."""

    def __init__(self) -> None:
        self.storage_type = settings.COLD_STORAGE_TYPE
        self.bucket = settings.COLD_STORAGE_BUCKET
        self.base_dir = Path("/app/archive")
        self._client = None
        self._client_context = None
        self._session = None

    async def _get_s3_client(self):
        if self._client is not None:
            return self._client

        from aiobotocore.session import get_session

        endpoint = settings.COLD_STORAGE_ENDPOINT
        self._session = get_session()
        self._client_context = self._session.create_client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=settings.COLD_STORAGE_ACCESS_KEY,
            aws_secret_access_key=settings.COLD_STORAGE_SECRET_KEY,
            region_name="us-east-1",
        )
        self._client = await self._client_context.__aenter__()
        try:
            await self._client.head_bucket(Bucket=self.bucket)
        except Exception:  # noqa: BLE001
            await self._client.create_bucket(Bucket=self.bucket)
        return self._client

    async def upload(self, key: str, data: bytes, storage_tier: str = "glacier") -> str:
        if self.storage_type in {"s3_glacier", "minio_cold"}:
            client = await self._get_s3_client()
            storage_class = "DEEP_ARCHIVE" if storage_tier == "glacier_deep" else "GLACIER"
            await client.put_object(Bucket=self.bucket, Key=key, Body=data, StorageClass=storage_class)
            return f"s3://{self.bucket}/{key}"

        self.base_dir.mkdir(parents=True, exist_ok=True)
        file_path = self.base_dir / key
        file_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(file_path, "wb") as fh:
            await fh.write(data)
        return str(file_path)

    async def download(self, archive_path: str) -> bytes:
        if archive_path.startswith("s3://"):
            _, rest = archive_path.split("s3://", 1)
            bucket, key = rest.split("/", 1)
            client = await self._get_s3_client()
            response = await client.get_object(Bucket=bucket, Key=key)
            return await response["Body"].read()

        async with aiofiles.open(archive_path, "rb") as fh:
            return await fh.read()

    async def close(self) -> None:
        if self._client_context is not None:
            await self._client_context.__aexit__(None, None, None)
            self._client = None
            self._client_context = None


class ArchiveService:
    def __init__(self) -> None:
        self.storage = ColdStorageBackend()
        self.scheduler: AsyncIOScheduler | None = None

    async def archive_expired_files(self, batch_size: int | None = None) -> int:
        if not settings.ARCHIVE_ENABLED:
            return 0

        batch = batch_size or settings.ARCHIVE_BATCH_SIZE
        cutoff = datetime.now(timezone.utc) - timedelta(days=settings.ARCHIVE_FILE_AGE_DAYS)
        archived = 0

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(File)
                .where(
                    File.expires_at.is_not(None),
                    File.expires_at < cutoff,
                    File.is_archived.is_(False),
                )
                .limit(batch)
            )
            files = result.scalars().all()

            for file_obj in files:
                try:
                    data = await encrypted_storage.download_bytes(file_obj.encrypted_path)
                    transformed = await self._transform_for_archive(data)
                    checksum = hashlib.sha256(transformed).hexdigest()

                    archive_key = (
                        f"files/{file_obj.id}/"
                        f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}.bin"
                    )
                    archive_path = await self.storage.upload(archive_key, transformed, storage_tier="glacier")

                    record = ArchiveRecord(
                        source_type="file",
                        source_id=file_obj.id,
                        source_table="files",
                        archive_path=archive_path,
                        archive_size_bytes=len(transformed),
                        archive_checksum=checksum,
                        storage_tier="glacier",
                        retention_until=datetime.now(timezone.utc)
                        + timedelta(days=settings.ARCHIVE_RETENTION_DAYS),
                        original_metadata={
                            "encrypted_path": file_obj.encrypted_path,
                            "original_name": file_obj.original_name,
                            "original_size": file_obj.original_size,
                            "mime_type": file_obj.mime_type,
                            "patient_id": file_obj.patient_id,
                            "compress": settings.ARCHIVE_COMPRESS,
                            "encrypt": settings.ARCHIVE_ENCRYPT,
                        },
                    )
                    session.add(record)

                    file_obj.is_archived = True
                    file_obj.archived_at = datetime.now(timezone.utc)

                    await encrypted_storage.delete(file_obj.encrypted_path)
                    await session.commit()
                    archived += 1
                    archived_total.labels(source_type="file").inc()
                except Exception as exc:  # noqa: BLE001
                    logger.error("Failed to archive file %s: %s", file_obj.id, exc)
                    archive_failures_total.labels(operation="archive", source_type="file").inc()
                    await session.rollback()

        return archived

    async def archive_old_audit_logs(self) -> int:
        if not settings.ARCHIVE_ENABLED:
            return 0

        cutoff = datetime.now(timezone.utc) - timedelta(days=settings.ARCHIVE_AUDIT_AGE_DAYS)
        audit_dir = Path("/app/audit_logs")
        if not audit_dir.exists():
            return 0

        archived = 0
        for log_file in audit_dir.glob("audit_*.log"):
            try:
                date_str = log_file.stem.replace("audit_", "")
                file_dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                if file_dt >= cutoff:
                    continue

                async with aiofiles.open(log_file, "rb") as fh:
                    data = await fh.read()

                transformed = await self._transform_for_archive(data)
                checksum = hashlib.sha256(transformed).hexdigest()
                archive_key = f"audit/{log_file.name}.bin"
                archive_path = await self.storage.upload(archive_key, transformed, storage_tier="glacier_deep")

                async with AsyncSessionLocal() as session:
                    record = ArchiveRecord(
                        source_type="audit",
                        source_id=0,
                        source_table="audit_logs",
                        archive_path=archive_path,
                        archive_size_bytes=len(transformed),
                        archive_checksum=checksum,
                        storage_tier="glacier_deep",
                        retention_until=datetime.now(timezone.utc)
                        + timedelta(days=settings.ARCHIVE_DEEP_RETENTION_DAYS),
                        original_metadata={
                            "filename": log_file.name,
                            "compress": settings.ARCHIVE_COMPRESS,
                            "encrypt": settings.ARCHIVE_ENCRYPT,
                        },
                    )
                    session.add(record)
                    await session.commit()

                log_file.unlink(missing_ok=True)
                archived += 1
                archived_total.labels(source_type="audit").inc()
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed to archive audit log %s: %s", log_file, exc)
                archive_failures_total.labels(operation="archive", source_type="audit").inc()

        return archived

    async def archive_deleted_users(self, batch_size: int | None = None) -> int:
        if not settings.ARCHIVE_ENABLED:
            return 0

        batch = batch_size or settings.ARCHIVE_BATCH_SIZE
        cutoff = datetime.now(timezone.utc) - timedelta(days=settings.ARCHIVE_DELETED_USER_AGE_DAYS)
        archived = 0

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(DeletedUser)
                .where(DeletedUser.deleted_at < cutoff, DeletedUser.is_archived.is_(False))
                .limit(batch)
            )
            users = result.scalars().all()

            for user in users:
                try:
                    anonymized_payload = {
                        "original_user_id": user.original_user_id,
                        "tenant_id": user.tenant_id,
                        "username_hash": hashlib.sha256(user.username.encode("utf-8")).hexdigest(),
                        "email_hash": hashlib.sha256(user.email.encode("utf-8")).hexdigest(),
                        "role": user.role,
                        "deleted_at": user.deleted_at.isoformat(),
                        "metadata": user.metadata_json,
                    }
                    data = str(anonymized_payload).encode("utf-8")
                    transformed = await self._transform_for_archive(data)

                    archive_key = f"users/{user.original_user_id}/{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}.bin"
                    archive_path = await self.storage.upload(archive_key, transformed, storage_tier="glacier")

                    record = ArchiveRecord(
                        source_type="user",
                        source_id=user.original_user_id,
                        source_table="deleted_users",
                        archive_path=archive_path,
                        archive_size_bytes=len(transformed),
                        archive_checksum=hashlib.sha256(transformed).hexdigest(),
                        storage_tier="glacier",
                        retention_until=datetime.now(timezone.utc)
                        + timedelta(days=settings.ARCHIVE_RETENTION_DAYS),
                        original_metadata={
                            "compress": settings.ARCHIVE_COMPRESS,
                            "encrypt": settings.ARCHIVE_ENCRYPT,
                            "anonymized": True,
                            "deleted_user_row_id": user.id,
                        },
                    )
                    session.add(record)

                    user.anonymized_at = datetime.now(timezone.utc)
                    user.archived_at = datetime.now(timezone.utc)
                    user.is_archived = True
                    user.username = f"archived_user_{user.original_user_id}"
                    user.email = f"archived_{user.original_user_id}@example.invalid"
                    await session.commit()

                    archived += 1
                    archived_total.labels(source_type="user").inc()
                except Exception as exc:  # noqa: BLE001
                    logger.error("Failed to archive deleted user %s: %s", user.id, exc)
                    archive_failures_total.labels(operation="archive", source_type="user").inc()
                    await session.rollback()

        return archived

    async def restore_from_archive(self, archive_id: str, user_id: str, reason: str) -> str:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(ArchiveRecord).where(ArchiveRecord.archive_id == archive_id))
            record = result.scalar_one_or_none()
            if record is None:
                raise ValueError(f"Archive record {archive_id} not found")

            restore_request = ArchiveRestoreRequest(
                archive_id=archive_id,
                requested_by=user_id,
                request_reason=reason,
                status="pending",
            )
            session.add(restore_request)
            await session.commit()
            await session.refresh(restore_request)

        asyncio.create_task(self._execute_restore(restore_request.id))
        return restore_request.request_id

    async def _execute_restore(self, request_pk: int) -> None:
        started = time.monotonic()
        async with AsyncSessionLocal() as session:
            req_res = await session.execute(
                select(ArchiveRestoreRequest).where(ArchiveRestoreRequest.id == request_pk)
            )
            request = req_res.scalar_one()

            rec_res = await session.execute(
                select(ArchiveRecord).where(ArchiveRecord.archive_id == request.archive_id)
            )
            record = rec_res.scalar_one()

            try:
                request.status = "processing"
                await session.commit()

                payload = await self.storage.download(record.archive_path)
                restored = await self._restore_transform(payload, record.original_metadata)

                if record.source_type == "file":
                    restored_path = await self._restore_file(record, restored)
                elif record.source_type == "audit":
                    restored_path = await self._restore_audit(record, restored)
                else:
                    restored_path = ""

                request.status = "completed"
                request.completed_at = datetime.now(timezone.utc)
                request.restored_path = restored_path

                record.status = "restored"
                record.restored_at = datetime.now(timezone.utc)
                record.restored_by = request.requested_by
                await session.commit()
            except Exception as exc:  # noqa: BLE001
                request.status = "failed"
                request.error_message = str(exc)
                request.completed_at = datetime.now(timezone.utc)
                await session.commit()
                archive_failures_total.labels(operation="restore", source_type=record.source_type).inc()
                logger.error("Archive restore failed for request %s: %s", request.request_id, exc)
            finally:
                restore_duration_seconds.observe(max(0.0, time.monotonic() - started))

    async def get_archive_stats(self) -> dict[str, Any]:
        async with AsyncSessionLocal() as session:
            by_type_rows = await session.execute(
                select(ArchiveRecord.source_type, func.count(ArchiveRecord.id)).group_by(ArchiveRecord.source_type)
            )
            by_type = {row[0]: int(row[1]) for row in by_type_rows.all()}

            size_row = await session.execute(select(func.coalesce(func.sum(ArchiveRecord.archive_size_bytes), 0)))
            total_size = int(size_row.scalar_one() or 0)

            restore_rows = await session.execute(
                select(ArchiveRestoreRequest.status, func.count(ArchiveRestoreRequest.id)).group_by(
                    ArchiveRestoreRequest.status
                )
            )
            restore_stats = {row[0]: int(row[1]) for row in restore_rows.all()}

        return {
            "total_archived": sum(by_type.values()),
            "by_type": by_type,
            "total_size_bytes": total_size,
            "total_size_gb": round(total_size / (1024 ** 3), 3),
            "restore_requests": restore_stats,
        }

    async def _transform_for_archive(self, raw: bytes) -> bytes:
        payload = raw
        if settings.ARCHIVE_COMPRESS:
            payload = gzip.compress(payload)
        if settings.ARCHIVE_ENCRYPT:
            payload = await self._encrypt_bytes(payload)
        return payload

    async def _restore_transform(self, payload: bytes, metadata: dict[str, Any]) -> bytes:
        data = payload
        if metadata.get("encrypt"):
            data = await self._decrypt_bytes(data)
        if metadata.get("compress"):
            data = gzip.decompress(data)
        return data

    async def _encrypt_bytes(self, data: bytes) -> bytes:
        with tempfile.TemporaryDirectory() as tmp:
            inp = Path(tmp) / "archive_input.bin"
            out = Path(tmp) / "archive_input.bin.age"
            async with aiofiles.open(inp, "wb") as fh:
                await fh.write(data)
            await crypto_manager.encrypt_file(inp, get_public_key(), out)
            async with aiofiles.open(out, "rb") as fh:
                return await fh.read()

    async def _decrypt_bytes(self, data: bytes) -> bytes:
        with tempfile.TemporaryDirectory() as tmp:
            inp = Path(tmp) / "archive_input.bin.age"
            out = Path(tmp) / "archive_input.bin"
            async with aiofiles.open(inp, "wb") as fh:
                await fh.write(data)
            await crypto_manager.decrypt_file(inp, PRIVATE_KEY_PATH, out)
            async with aiofiles.open(out, "rb") as fh:
                return await fh.read()

    async def _restore_file(self, record: ArchiveRecord, data: bytes) -> str:
        key = record.original_metadata.get("encrypted_path") or (
            f"restored/{record.source_id}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}.age"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "restored_file.bin"
            async with aiofiles.open(path, "wb") as fh:
                await fh.write(data)
            await encrypted_storage.upload(key=key, file_path=path, content_type="application/octet-stream")
        return key

    async def _restore_audit(self, record: ArchiveRecord, data: bytes) -> str:
        filename = record.original_metadata.get("filename", f"restored_{record.archive_id}.log")
        restore_path = Path("/app/audit_logs") / f"restored_{filename}"
        restore_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(restore_path, "wb") as fh:
            await fh.write(data)
        return str(restore_path)

    def start(self) -> None:
        if self.scheduler is not None and self.scheduler.running:
            return

        self.scheduler = AsyncIOScheduler(timezone="UTC")
        self.scheduler.add_job(self.archive_expired_files, "interval", hours=1, id="archive_files")
        self.scheduler.add_job(self.archive_old_audit_logs, "cron", hour=2, minute=0, id="archive_audits")
        self.scheduler.add_job(self.archive_deleted_users, "interval", hours=1, id="archive_deleted_users")
        self.scheduler.start()
        logger.info("Archive scheduler started")

    async def stop(self) -> None:
        if self.scheduler is not None and self.scheduler.running:
            self.scheduler.shutdown(wait=False)
        self.scheduler = None
        await self.storage.close()


archive_service = ArchiveService()
