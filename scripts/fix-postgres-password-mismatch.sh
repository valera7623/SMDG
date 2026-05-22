#!/usr/bin/env bash
# Синхронизирует пароль роли smdg_user в Postgres с secrets/postgres_password.txt
#
# Симптом: alembic / smdg падает с
#   FATAL: password authentication failed for user "smdg_user"
# Причина: том pgdata создан с другим паролем, а файл secret уже сменили.
#
# Запуск на VPS в каталоге проекта (db должен быть запущен):
#   ./scripts/fix-postgres-password-mismatch.sh
#
# Требует: локальный socket в контейнере db (trust), как в образе postgres:15-alpine.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

SECRET_FILE="${ROOT}/secrets/postgres_password.txt"
if [[ ! -f "$SECRET_FILE" ]]; then
  echo "Нет файла: $SECRET_FILE" >&2
  exit 1
fi

NEW_PASS="$(tr -d '\n\r' < "$SECRET_FILE")"
if [[ -z "$NEW_PASS" ]]; then
  echo "Пустой пароль в $SECRET_FILE" >&2
  exit 1
fi

echo "Обновляем пароль smdg_user в Postgres (пароль из secrets/postgres_password.txt)..."
# Экранируем одинарные кавычки для SQL
SAFE_PASS="${NEW_PASS//\'/\'\'}"

docker compose exec -T db psql -U smdg_user -d smdg -v ON_ERROR_STOP=1 \
  -c "ALTER USER smdg_user WITH PASSWORD '${SAFE_PASS}';"

echo "OK. Перезапустите приложение: docker compose up -d smdg"
