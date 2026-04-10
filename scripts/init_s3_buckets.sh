#!/bin/bash
# scripts/init_s3_buckets.sh
# Инициализация S3/MinIO бакетов при старте

set -euo pipefail

echo "🪣 S3 Bucket Initialization..."

# Проверяем, включён ли S3 режим
if [ "${S3_ENABLED:-false}" != "true" ]; then
    echo "ℹ️  S3 отключён (S3_ENABLED=false). Пропускаем инициализацию бакетов."
    exit 0
fi

# Проверяем обязательные переменные
if [ -z "${S3_ENDPOINT_URL:-}" ]; then
    echo "❌ S3_ENDPOINT_URL не установлен!"
    exit 1
fi

if [ -z "${S3_ACCESS_KEY:-}" ] || [ -z "${S3_SECRET_KEY:-}" ]; then
    echo "❌ S3_ACCESS_KEY или S3_SECRET_KEY не установлены!"
    exit 1
fi

echo "📡 Подключение к S3: ${S3_ENDPOINT_URL}"

# Определяем, используем ли MinIO (локальный) или внешний S3
IS_MINIO=false
if echo "${S3_ENDPOINT_URL}" | grep -qE "minio|localhost|127\.0\.0\.1"; then
    IS_MINIO=true
fi

# Создаём Python скрипт для создания бакетов
python3 << 'PYTHON_SCRIPT'
import asyncio
import sys
import os

async def init_buckets():
    from aiobotocore.session import get_session

    endpoint_url = os.environ["S3_ENDPOINT_URL"]
    access_key = os.environ["S3_ACCESS_KEY"]
    secret_key = os.environ["S3_SECRET_KEY"]
    region = os.environ.get("S3_REGION", "us-east-1")
    use_ssl = os.environ.get("S3_USE_SSL", "false").lower() == "true"

    buckets = [
        os.environ.get("S3_BUCKET_ENCRYPTED", "smdg-encrypted"),
        os.environ.get("S3_BUCKET_UPLOADS", "smdg-uploads"),
        os.environ.get("S3_BUCKET_DECRYPTED", "smdg-decrypted"),
    ]

    session = get_session()
    protocol = "https" if use_ssl else "http"
    endpoint = endpoint_url if endpoint_url.startswith("http") else f"{protocol}://{endpoint_url}"

    async with session.create_client(
        's3',
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region,
    ) as client:
        for bucket in buckets:
            try:
                await client.head_bucket(Bucket=bucket)
                print(f"✅ Бакет {bucket} уже существует")
            except Exception:
                try:
                    await client.create_bucket(Bucket=bucket)
                    print(f"✅ Бакет {bucket} создан")

                    # Для MinIO устанавливаем политику публичного чтения (только для dev)
                    if os.environ.get("DEV_MODE", "false").lower() == "true":
                        policy = {
                            "Version": "2012-10-17",
                            "Statement": [
                                {
                                    "Effect": "Allow",
                                    "Principal": {"AWS": "*"},
                                    "Action": ["s3:GetObject"],
                                    "Resource": [f"arn:aws:s3:::{bucket}/*"]
                                }
                            ]
                        }
                        import json
                        await client.put_bucket_policy(Bucket=bucket, Policy=json.dumps(policy))
                        print(f"   📋 Политика публичного чтения установлена (dev mode)")

                except Exception as e:
                    print(f"❌ Ошибка создания бакета {bucket}: {e}", file=sys.stderr)
                    sys.exit(1)

        print("🎉 Все бакеты инициализированы успешно")

asyncio.run(init_buckets())
PYTHON_SCRIPT

echo "✅ Инициализация S3 завершена"
