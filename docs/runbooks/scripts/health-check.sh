#!/usr/bin/env bash
# Comprehensive health check for SMDG.

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "========================================="
echo "SMDG Health Check"
echo "Time: $(date)"
echo "========================================="

check_service() {
    local name="$1"
    local command="$2"
    if eval "$command" &>/dev/null; then
        echo -e "${GREEN}✓${NC} ${name}"
    else
        echo -e "${RED}✗${NC} ${name}"
        return 1
    fi
}

echo -e "\n[1/8] Docker Containers"
check_service "smdg container exists" "docker compose ps --quiet smdg"
check_service "db container exists" "docker compose ps --quiet db"
check_service "redis container exists" "docker compose ps --quiet redis"
check_service "nginx container exists" "docker compose ps --quiet nginx"

echo -e "\n[2/8] Health Endpoints"
check_service "Health endpoint" "curl -fsS http://localhost:8000/health"
check_service "Readiness endpoint" "curl -fsS http://localhost:8000/health/ready"
check_service "Liveness endpoint" "curl -fsS http://localhost:8000/health/live"

echo -e "\n[3/8] Database"
check_service "PostgreSQL ready" "docker compose exec -T db pg_isready -U smdg_user"
check_service "DB size < 100GB" "docker compose exec -T db psql -U smdg_user -d smdg -tAc \"SELECT pg_database_size('smdg') < 100*1024*1024*1024\" | grep -q t"

echo -e "\n[4/8] Redis"
check_service "Redis ping" "docker compose exec -T redis redis-cli PING | grep -q PONG"

echo -e "\n[5/8] Storage"
check_service "Disk usage under 80%" "[ $(df -h / | awk 'NR==2 {print $5}' | tr -d '%') -lt 80 ]"

echo -e "\n[6/8] Recent API Errors"
RECENT_ERRORS=$(docker compose logs smdg --since 5m 2>&1 | grep -i error | wc -l || true)
if [ "${RECENT_ERRORS}" -gt 0 ]; then
    echo -e "${YELLOW}⚠${NC} ${RECENT_ERRORS} error lines in last 5 minutes"
    docker compose logs smdg --since 5m | grep -i error | tail -5 || true
else
    echo -e "${GREEN}✓${NC} no recent errors"
fi

echo -e "\n[7/8] Performance Snapshot"
ACTIVE_REQUESTS=$(curl -s http://localhost:8000/metrics 2>/dev/null | grep -E "http_requests_in_progress|active_requests" | awk '{print $2}' | head -1)
echo "Active requests: ${ACTIVE_REQUESTS:-unknown}"

echo -e "\n[8/8] Backup Status"
LAST_BACKUP=$(ls -1t /backups/smdg 2>/dev/null | head -1 || true)
if [ -n "${LAST_BACKUP}" ]; then
    echo -e "${GREEN}✓${NC} latest backup: ${LAST_BACKUP}"
else
    echo -e "${YELLOW}⚠${NC} backup directory is empty or unavailable"
fi

echo -e "\n========================================="
echo "Health check completed"
echo "========================================="
