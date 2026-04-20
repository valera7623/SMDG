#!/usr/bin/env python3
"""
Проверка и подсказки при смене DEPLOYMENT_TYPE.

Не изменяет данные в БД автоматически: выводит чеклист для администратора.
Запуск из корня проекта:

  poetry run python scripts/migrate_deployment_type.py --target intl
"""
from __future__ import annotations

import argparse
import os
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="Миграция / проверка профиля развёртывания")
    parser.add_argument(
        "--target",
        choices=("russia", "intl", "single", "saas"),
        help="Целевой DEPLOYMENT_TYPE",
    )
    args = parser.parse_args()

    current = os.getenv("DEPLOYMENT_TYPE", "single")
    print(f"Текущий DEPLOYMENT_TYPE (env): {current}")
    if args.target:
        print(f"Целевой профиль: {args.target}")
        if args.target == "russia":
            print(
                "- Установите S3_ENABLED=false и перенесите данные из облака на локальный том.\n"
                "- Включите политику 2FA для всех учётных записей (MATВОЗ / CLI).\n"
                "- Проверьте срок аудита: 1095 дней при AUDIT_3_YEARS в матрице."
            )
        if args.target == "intl":
            print(
                "- Настройте S3/MinIO и секреты доступа.\n"
                "- Включите процедуры GDPR (удаление / portability) при необходимости."
            )
        if args.target == "single":
            print("- Рекомендуется локальное хранилище; отключите S3 если не нужен.")
        if args.target == "saas":
            print(
                "- Требуется рабочий S3 endpoint и ключи.\n"
                "- Убедитесь, что multi-tenant миграции применены и биллинг подключён отдельно."
            )
    print("Готово. Примените переменные в .env и выполните перезапуск контейнеров.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
