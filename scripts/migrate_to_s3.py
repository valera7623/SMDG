#!/usr/bin/env python3
"""
scripts/migrate_to_s3.py
Миграция зашифрованных файлов из локальной файловой системы в S3/MinIO.

Использование:
    # Dry-run (проверка без загрузки)
    python -m app.cli migrate-to-s3 --dry-run

    # Реальная миграция
    python -m app.cli migrate-to-s3

    # Миграция с удалением локальных файлов после успешной загрузки
    python -m app.cli migrate-to-s3 --delete-local
"""

import asyncio
import os
import sys
from pathlib import Path
from typing import List, Dict, Any
import logging
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


async def migrate_to_s3(
    encrypted_dir: Path,
    s3_endpoint: str,
    s3_access_key: str,
    s3_secret_key: str,
    s3_bucket: str,
    s3_region: str = "us-east-1",
    s3_use_ssl: bool = False,
    delete_local: bool = False,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Миграция файлов из локальной директории в S3.

    Args:
        encrypted_dir: Локальная директория с зашифрованными файлами
        s3_endpoint: URL S3 endpoint
        s3_access_key: Access key
        s3_secret_key: Secret key
        s3_bucket: Имя бакета
        s3_region: Регион
        s3_use_ssl: Использовать HTTPS
        delete_local: Удалить локальные файлы после миграции
        dry_run: Только показать что будет сделано (без реальных действий)

    Returns:
        Статистика миграции
    """
    from aiobotocore.session import get_session
    import aiofiles

    stats = {
        "total_files": 0,
        "migrated": 0,
        "skipped": 0,
        "errors": [],
        "total_bytes": 0,
        "started_at": datetime.now().isoformat(),
        "completed_at": None,
    }

    if not encrypted_dir.exists():
        logger.warning(f"❌ Директория {encrypted_dir} не существует")
        return stats

    # Собираем файлы
    local_files = []
    for f in encrypted_dir.iterdir():
        if f.is_file():
            local_files.append(f)

    stats["total_files"] = len(local_files)
    total_size = sum(f.stat().st_size for f in local_files)
    stats["total_bytes"] = total_size

    logger.info(f"📂 Найдено {len(local_files)} файлов ({total_size / 1024 / 1024:.2f} MB)")

    if dry_run:
        logger.info("🔍 DRY RUN — реальные действия не выполняются")
        for f in local_files:
            logger.info(f"   📤 Будет загружен: {f.name} ({f.stat().st_size} bytes)")
        stats["skipped"] = len(local_files)
        stats["completed_at"] = datetime.now().isoformat()
        return stats

    # Подключаемся к S3
    protocol = "https" if s3_use_ssl else "http"
    endpoint = s3_endpoint if s3_endpoint.startswith("http") else f"{protocol}://{s3_endpoint}"

    session = get_session()

    async with session.create_client(
        's3',
        endpoint_url=endpoint,
        aws_access_key_id=s3_access_key,
        aws_secret_access_key=s3_secret_key,
        region_name=s3_region,
    ) as client:
        # Проверяем/создаём бакет
        try:
            await client.head_bucket(Bucket=s3_bucket)
            logger.info(f"✅ Бакет {s3_bucket} существует")
        except Exception:
            logger.info(f"🪣 Создаю бакет {s3_bucket}...")
            await client.create_bucket(Bucket=s3_bucket)
            logger.info(f"✅ Бакет {s3_bucket} создан")

        # Миграция файлов
        for i, local_file in enumerate(local_files, 1):
            try:
                key = local_file.name  # Имя файла = S3 object key

                # Проверяем, существует ли уже файл в S3
                try:
                    await client.head_object(Bucket=s3_bucket, Key=key)
                    logger.info(f"⏭️  [{i}/{len(local_files)}] {key} уже в S3 — пропускаем")
                    stats["skipped"] += 1
                    continue
                except Exception:
                    pass  # Файл не найден в S3 — загружаем

                # Читаем и загружаем
                async with aiofiles.open(local_file, 'rb') as f:
                    content = await f.read()

                await client.put_object(
                    Bucket=s3_bucket,
                    Key=key,
                    Body=content,
                    ContentType="application/octet-stream"
                )

                stats["migrated"] += 1
                logger.info(f"✅ [{i}/{len(local_files)}] {key} загружен ({len(content)} bytes)")

                # Удаляем локальный файл если запрошено
                if delete_local:
                    local_file.unlink()
                    logger.info(f"   🗑️  Локальный файл удалён: {key}")

            except Exception as e:
                error_msg = f"Ошибка миграции {local_file.name}: {e}"
                stats["errors"].append({"file": local_file.name, "error": str(e)})
                logger.error(f"❌ {error_msg}")

    stats["completed_at"] = datetime.now().isoformat()

    # Итог
    logger.info("=" * 60)
    logger.info("📊 Итоги миграции:")
    logger.info(f"   Всего файлов: {stats['total_files']}")
    logger.info(f"   Мигрировано: {stats['migrated']}")
    logger.info(f"   Пропущено: {stats['skipped']}")
    logger.info(f"   Ошибок: {len(stats['errors'])}")
    logger.info(f"   Общий размер: {stats['total_bytes'] / 1024 / 1024:.2f} MB")
    logger.info("=" * 60)

    if stats["errors"]:
        logger.warning("⚠️ Файлы с ошибками:")
        for err in stats["errors"]:
            logger.warning(f"   - {err['file']}: {err['error']}")

    return stats


async def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Миграция зашифрованных файлов в S3")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Показать что будет сделано без реальных действий"
    )
    parser.add_argument(
        "--delete-local",
        action="store_true",
        help="Удалить локальные файлы после успешной миграции"
    )
    parser.add_argument(
        "--encrypted-dir",
        type=str,
        default=os.environ.get("ENCRYPTED_DIR", "/app/encrypted"),
        help="Директория с зашифрованными файлами"
    )
    parser.add_argument(
        "--s3-endpoint",
        type=str,
        default=os.environ.get("S3_ENDPOINT_URL"),
        help="S3 endpoint URL"
    )
    parser.add_argument(
        "--s3-access-key",
        type=str,
        default=os.environ.get("S3_ACCESS_KEY"),
        help="S3 access key"
    )
    parser.add_argument(
        "--s3-secret-key",
        type=str,
        default=os.environ.get("S3_SECRET_KEY"),
        help="S3 secret key"
    )
    parser.add_argument(
        "--s3-bucket",
        type=str,
        default=os.environ.get("S3_BUCKET_ENCRYPTED", "smdg-encrypted"),
        help="S3 bucket name"
    )
    parser.add_argument(
        "--s3-region",
        type=str,
        default=os.environ.get("S3_REGION", "us-east-1"),
        help="S3 region"
    )

    args = parser.parse_args()

    # Валидация
    if not args.dry_run:
        if not args.s3_endpoint:
            parser.error("--s3-endpoint или S3_ENDPOINT_URL обязателен")
        if not args.s3_access_key:
            parser.error("--s3-access-key или S3_ACCESS_KEY обязателен")
        if not args.s3_secret_key:
            parser.error("--s3-secret-key или S3_SECRET_KEY обязателен")

    encrypted_dir = Path(args.encrypted_dir)
    if not encrypted_dir.exists():
        print(f"❌ Директория не найдена: {encrypted_dir}")
        sys.exit(1)

    stats = await migrate_to_s3(
        encrypted_dir=encrypted_dir,
        s3_endpoint=args.s3_endpoint,
        s3_access_key=args.s3_access_key,
        s3_secret_key=args.s3_secret_key,
        s3_bucket=args.s3_bucket,
        s3_region=args.s3_region,
        delete_local=args.delete_local,
        dry_run=args.dry_run,
    )

    if stats["errors"]:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
