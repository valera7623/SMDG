#!/usr/bin/env bash

set -e

ACTION="${1:-status}"
TARGET="${2:-1}"

NGINX_CONTAINER="smdg-scale-nginx-lb-1"
CONF_FILE="/etc/nginx/conf.d/default.conf"
BACKUP_DIR="/etc/nginx/backups"

case "$ACTION" in
    status)
        echo "📊 Current upstream configuration:"
        docker exec "$NGINX_CONTAINER" grep -A5 "upstream smdg_backend" "$CONF_FILE"
        ;;
    
    backup)
        docker exec "$NGINX_CONTAINER" mkdir -p "$BACKUP_DIR"
        BACKUP_FILE="$BACKUP_DIR/default.conf.$(date +%Y%m%d_%H%M%S)"
        docker exec "$NGINX_CONTAINER" cp "$CONF_FILE" "$BACKUP_FILE"
        echo "✅ Backup saved: $BACKUP_FILE"
        ;;
    
    single)
        echo "🔄 Switching traffic to instance smdg-scale-smdg-$TARGET only"
        docker exec "$NGINX_CONTAINER" cp "$CONF_FILE" "$BACKUP_DIR/default.conf.pre_single_$TARGET"
        docker exec "$NGINX_CONTAINER" sed -i "s/server smdg:8000/server smdg-scale-smdg-$TARGET:8000/g" "$CONF_FILE"
        docker exec "$NGINX_CONTAINER" nginx -t && docker exec "$NGINX_CONTAINER" nginx -s reload
        echo "✅ Traffic now goes only to instance $TARGET"
        ;;
    
    all)
        echo "🔄 Restoring load balancing across all instances"
        docker exec "$NGINX_CONTAINER" sed -i "s/server smdg-scale-smdg-[0-9]:8000/server smdg:8000/g" "$CONF_FILE"
        docker exec "$NGINX_CONTAINER" nginx -t && docker exec "$NGINX_CONTAINER" nginx -s reload
        echo "✅ Load balancing restored"
        ;;
    
    restore)
        if [ -z "$TARGET" ] || [ "$TARGET" = "latest" ]; then
            LATEST=$(docker exec "$NGINX_CONTAINER" ls -t "$BACKUP_DIR"/default.conf.* 2>/dev/null | head -1)
            TARGET="$LATEST"
        fi
        echo "🔄 Restoring from backup: $TARGET"
        docker exec "$NGINX_CONTAINER" cp "$TARGET" "$CONF_FILE"
        docker exec "$NGINX_CONTAINER" nginx -t && docker exec "$NGINX_CONTAINER" nginx -s reload
        echo "✅ Restored"
        ;;
    
    *)
        echo "Usage: $0 {status|backup|single <1-3>|all|restore [backup-file]}"
        exit 1
        ;;
esac

# Show current distribution
echo ""
echo "📊 Current traffic distribution (10 requests):"
for i in {1..10}; do
  curl -ks https://localhost:18443/health/ready | jq -r '.instance_id'
done | sort | uniq -c
