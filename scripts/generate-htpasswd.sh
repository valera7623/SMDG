#!/usr/bin/env bash
# =============================================================================
# generate-htpasswd.sh — создаёт файл Basic Auth для nginx location'ов,
# защищающих internal observability-сервисы SMDG (Jaeger, Prometheus и т. п.).
#
# Зачем это нужно:
#   Jaeger и Prometheus не имеют встроенной аутентификации. В production
#   их UI проксируются через nginx с ``auth_basic`` — этот скрипт создаёт
#   соответствующий ``.htpasswd`` файл. Хранится в ``secrets/`` (уже в
#   .gitignore) и монтируется read-only в контейнер nginx.
#
# Использование:
#   bash scripts/generate-htpasswd.sh <service> <username>
#
# Примеры:
#   bash scripts/generate-htpasswd.sh jaeger     observability
#   bash scripts/generate-htpasswd.sh prometheus metrics-admin
#
# Куда пишется результат:
#   secrets/.htpasswd-<service>
#   (смонтирован в nginx как /etc/nginx/.htpasswd-<service>)
#
# После создания файла обязательно перезапустить nginx, чтобы подхватить
# новые учётные данные:
#   docker compose -f docker-compose.yml -f docker-compose.prod.yml \
#       restart nginx
# =============================================================================

set -euo pipefail

SERVICE="${1:-}"
USERNAME="${2:-}"

if [[ -z "$SERVICE" || -z "$USERNAME" ]]; then
    cat <<'USAGE' >&2
Usage: bash scripts/generate-htpasswd.sh <service> <username>

Supported services (соответствуют location'ам в nginx-zero-downtime.conf):
  jaeger      → /jaeger/
  prometheus  → /prometheus/

Examples:
  bash scripts/generate-htpasswd.sh jaeger     observability
  bash scripts/generate-htpasswd.sh prometheus metrics-admin
USAGE
    exit 1
fi

# Разрешённые значения service — чтобы опечатка не создала «невидимый»
# файл, который nginx никогда не прочитает.
case "$SERVICE" in
    jaeger|prometheus) ;;
    *)
        echo "❌ Unknown service: '$SERVICE'. Allowed: jaeger, prometheus" >&2
        exit 1
        ;;
esac

OUTPUT_FILE="secrets/.htpasswd-${SERVICE}"

mkdir -p secrets

# Используем локальный htpasswd, если доступен; иначе — Docker-fallback на
# образе httpd:alpine. bcrypt (-B) — более стойкий, чем MD5-дефолт.
if command -v htpasswd >/dev/null 2>&1; then
    # -c: создать новый файл (перезапишет существующий для этого user'а).
    # -B: bcrypt.
    htpasswd -cB "$OUTPUT_FILE" "$USERNAME"
else
    echo "ℹ️  htpasswd не найден локально, используем Docker-контейнер httpd..." >&2
    read -r -s -p "Password: " PASSWORD
    echo "" >&2
    docker run --rm httpd:2.4-alpine \
        htpasswd -nbB "$USERNAME" "$PASSWORD" \
        > "$OUTPUT_FILE"
    unset PASSWORD
fi

chmod 640 "$OUTPUT_FILE"

cat <<INFO >&2

✅ Создан $OUTPUT_FILE (service=$SERVICE, user=$USERNAME)

Перезапустите nginx, чтобы применить изменения:
  docker compose -f docker-compose.yml -f docker-compose.prod.yml restart nginx

Доступ: https://<DOMAIN>/${SERVICE}/ → Basic Auth (${USERNAME} / <заданный пароль>)
INFO
