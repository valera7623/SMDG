# app/core/s3_lifecycle.py
"""
S3 Lifecycle Policy Manager.

Управляет правилами автоматического удаления файлов через S3 Lifecycle Policies.
Заменяет FileCleanupManager при использовании S3/MinIO хранилища.

Преимущества:
- Удаление на стороне S3 — не требует running application
- Точное соблюдение TTL — S3 удаляет файлы автоматически
- Не потребляет ресурсы приложения — нет фоновых задач
- Работает даже когда приложение остановлено
"""

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class S3LifecyclePolicyManager:
    """
    Менеджер S3 Lifecycle Policies для автоматического удаления файлов.

    Правила удаления:
    - .txt, .age: 30 дней
    - .jpg, .png: 180 дней
    - .pdf: 90 дней
    - .dcm (DICOM): 365 дней
    - Остальные: настраиваемый TTL по умолчанию
    """

    def __init__(
        self,
        s3_client,
        bucket: str,
        default_ttl_days: int = 30,
        custom_policies: Optional[Dict[str, int]] = None,
    ):
        """
        Args:
            s3_client: aiobotocore S3 клиент (или boto3 client для sync)
            bucket: Имя бакета
            default_ttl_days: TTL по умолчанию (дни)
            custom_policies: Кастомные правила {extension: ttl_days}
        """
        self.s3_client = s3_client
        self.bucket = bucket
        self.default_ttl_days = default_ttl_days

        # Политики хранения по типам файлов
        self.retention_policies = custom_policies or {
            '.txt': 30,
            '.pdf': 90,
            '.dcm': 365,
            '.age': 30,
            '.jpg': 180,
            '.jpeg': 180,
            '.png': 180,
            '.gif': 180,
            '.tiff': 180,
            '.tif': 180,
        }

        logger.info(
            f"📅 S3LifecyclePolicyManager инициализирован для бакета '{bucket}' "
            f"(default TTL: {default_ttl_days} дней)"
        )

    async def apply_lifecycle_rules(self) -> Dict:
        """
        Применить Lifecycle Policies к бакету.

        Создаёт правила для каждого типа файлов + default rule.
        S3 автоматически удаляет файлы по истечении TTL.

        Returns:
            Dict с информацией о применённых правилах
        """
        try:
            rules = self._build_lifecycle_rules()

            lifecycle_config = {
                'Rules': rules
            }

            await self.s3_client.put_bucket_lifecycle_configuration(
                Bucket=self.bucket,
                LifecycleConfiguration=lifecycle_config
            )

            logger.info(
                f"✅ Применено {len(rules)} S3 Lifecycle правил для бакета '{self.bucket}'"
            )

            return {
                "success": True,
                "bucket": self.bucket,
                "rules_count": len(rules),
                "rules": [
                    {
                        "id": rule["ID"],
                        "prefix": rule.get("Filter", {}).get("Prefix", ""),
                        "expiration_days": rule["Expiration"]["Days"],
                    }
                    for rule in rules
                ]
            }

        except Exception as e:
            logger.error(f"❌ Ошибка применения S3 Lifecycle правил: {e}")
            return {
                "success": False,
                "error": str(e),
                "bucket": self.bucket,
            }

    def _build_lifecycle_rules(self) -> List[Dict]:
        """
        Построить список Lifecycle правил.

        Каждое правило:
        - ID: уникальное имя
        - Filter: по расширению файла (Prefix)
        - Expiration: Days — через сколько дней удалить
        - Status: Enabled
        """
        rules = []

        # Default rule для всех файлов без специального правила
        rules.append({
            'ID': 'default-expiration',
            'Filter': {'Prefix': ''},  # все файлы
            'Status': 'Enabled',
            'Expiration': {'Days': self.default_ttl_days},
        })

        # Rules для конкретных расширений
        for ext, ttl_days in self.retention_policies.items():
            # Пропускаем default — уже добавлен
            if ext == '.age' and ttl_days == self.default_ttl_days:
                continue

            rule_id = f'expire-{ext.lstrip(".")}-after-{ttl_days}d'
            rules.append({
                'ID': rule_id,
                'Filter': {'Prefix': ext.lower()},  # Filter по расширению
                'Status': 'Enabled',
                'Expiration': {'Days': ttl_days},
            })

        return rules

    async def get_lifecycle_rules(self) -> List[Dict]:
        """Получить текущие Lifecycle правила бакета."""
        try:
            response = await self.s3_client.get_bucket_lifecycle_configuration(
                Bucket=self.bucket
            )
            return response.get('Rules', [])
        except Exception as e:
            logger.warning(f"Ошибка получения Lifecycle правил: {e}")
            return []

    async def delete_lifecycle_rules(self) -> bool:
        """Удалить все Lifecycle правила бакета."""
        try:
            await self.s3_client.delete_bucket_lifecycle(Bucket=self.bucket)
            logger.info(f"🗑️ Удалены все Lifecycle правила для бакета '{self.bucket}'")
            return True
        except Exception as e:
            logger.error(f"Ошибка удаления Lifecycle правил: {e}")
            return False

    async def get_lifecycle_status(self) -> Dict:
        """
        Получить статус Lifecycle политик.

        Returns:
            Dict с информацией о правилах и файлах, подлежащих удалению.
        """
        rules = await self.get_lifecycle_rules()

        return {
            "bucket": self.bucket,
            "rules_count": len(rules),
            "rules": [
                {
                    "id": rule.get("ID"),
                    "expiration_days": rule.get("Expiration", {}).get("Days"),
                    "status": rule.get("Status"),
                }
                for rule in rules
            ],
            "default_ttl_days": self.default_ttl_days,
            "retention_policies": self.retention_policies,
        }

    def get_ttl_for_file(self, filename: str) -> int:
        """
        Получить TTL для файла по его имени.

        Args:
            filename: Имя файла (с расширением)

        Returns:
            TTL в днях
        """
        filename_lower = filename.lower()

        for ext, ttl in self.retention_policies.items():
            if filename_lower.endswith(ext):
                return ttl

        return self.default_ttl_days
