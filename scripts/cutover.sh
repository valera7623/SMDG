#!/usr/bin/env bash
# Blue/green, canary, and rollback for the smdg-scale stack (docker-compose.scale.yml).
# Copies upstream templates into nginx/nginx-load-balancer.conf and reloads nginx-lb.
#
# For an edge single-container in-place upstream swap, use: ./scripts/cutover_edge.sh
# For include-based upstream (upstream-target.conf), use:   ./scripts/cutover_include.sh
#
# Usage: ./scripts/cutover.sh {status|blue|green|canary|rollback} [instance]

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

TARGET="${1:-status}"
INSTANCE="${2:-2}"

COMPOSE_PROJECT="smdg-scale"
COMPOSE_FILE="docker-compose.scale.yml"
NGINX_CONFIG_HOST="./nginx/nginx-load-balancer.conf"
NGINX_CONFIGS_DIR="./nginx/upstreams"
PUBLIC_HEALTH_URL="https://localhost:18443/health/ready"

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

show_status() {
    log_info "Current upstream configuration:"
    grep "server " "$NGINX_CONFIG_HOST" | grep -v "^\s*#" | head -1 || true

    echo ""
    log_info "Current traffic distribution (10 requests):"
    for i in {1..10}; do
        curl -ks "$PUBLIC_HEALTH_URL" | jq -r '.instance_id' 2>/dev/null
    done | sort | uniq -c | while read line; do
        echo "  $line"
    done
}

switch_to_all() {
    log_info "Switching to load balancing across ALL instances"
    cp "$NGINX_CONFIGS_DIR/load-balancer-all.conf" "$NGINX_CONFIG_HOST"
}

switch_to_single() {
    local instance=$1
    log_info "Switching traffic to instance smdg-scale-smdg-${instance} only"
    cp "$NGINX_CONFIGS_DIR/load-balancer-single-${instance}.conf" "$NGINX_CONFIG_HOST"
}

reload_nginx() {
    log_info "Testing nginx configuration..."
    docker compose -p "$COMPOSE_PROJECT" -f "$COMPOSE_FILE" exec nginx-lb nginx -t 2>&1 | grep -q "successful" || {
        log_error "Configuration test failed"
        exit 1
    }
    log_success "Configuration test passed"

    log_info "Reloading nginx..."
    docker compose -p "$COMPOSE_PROJECT" -f "$COMPOSE_FILE" exec nginx-lb nginx -s reload
    log_success "Nginx reloaded"
}

wait_for_health() {
    local max_attempts=60
    local attempt=1

    log_info "Waiting for health check to pass (up to 60 seconds)..."
    while [ $attempt -le $max_attempts ]; do
        local response=$(curl -ks "$PUBLIC_HEALTH_URL" 2>/dev/null)
        if echo "$response" | jq -e '.ready == true' >/dev/null 2>&1; then
            local instance=$(echo "$response" | jq -r '.instance_id' | cut -c1-12)
            log_success "Health check passed on attempt $attempt (instance: $instance)"
            return 0
        fi
        printf "."
        sleep 1
        attempt=$((attempt + 1))
    done
    echo ""
    log_error "Health check failed after $max_attempts attempts"
    return 1
}

case "$TARGET" in
    status)
        show_status
        ;;

    blue)
        log_info "🔵 BLUE DEPLOYMENT - Load balancing across all instances"
        switch_to_all
        reload_nginx
        wait_for_health
        show_status
        log_success "Blue deployment active"
        ;;

    green)
        log_info "🟢 GREEN DEPLOYMENT - Single instance (smdg-${INSTANCE})"
        switch_to_single "$INSTANCE"
        reload_nginx
        wait_for_health
        show_status
        log_success "Green deployment active on instance ${INSTANCE}"
        ;;

    canary)
        log_info "🔶 CANARY - Testing instance ${INSTANCE}"
        switch_to_single "$INSTANCE"
        reload_nginx
        sleep 5
        show_status
        ;;

    rollback)
        log_info "Rolling back to blue deployment..."
        switch_to_all
        reload_nginx
        wait_for_health
        show_status
        log_success "Rollback complete"
        ;;

    *)
        echo "Usage: $0 {status|blue|green|canary|rollback} [instance]"
        exit 1
        ;;
esac
