#!/usr/bin/env bash
# =============================================================================
# scripts/rolling_update.sh
#
# Обёртка для ручного запуска rolling update в разных окружениях:
#   • Docker Compose (standalone)  → делегирует в zero_downtime_deploy.sh
#   • Docker Swarm                 → docker service update с update_config
#   • Kubernetes                   → kubectl set image + rollout status
#
# Определяет тип окружения автоматически (или через $DEPLOY_TARGET).
#
# Usage:
#   ./scripts/rolling_update.sh 4.0.1
#   DEPLOY_TARGET=swarm ./scripts/rolling_update.sh v4.0.1
#   DEPLOY_TARGET=k8s K8S_NAMESPACE=smdg ./scripts/rolling_update.sh v4.0.1
# =============================================================================

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}/.."

NEW_TAG="${1:-${IMAGE_TAG:-latest}}"
DEPLOY_TARGET="${DEPLOY_TARGET:-auto}"
STACK_NAME="${STACK_NAME:-smdg}"
SERVICE_NAME="${SERVICE_NAME:-smdg_smdg}"
K8S_NAMESPACE="${K8S_NAMESPACE:-smdg}"
K8S_DEPLOYMENT="${K8S_DEPLOYMENT:-smdg}"
DOCKER_USERNAME="${DOCKER_USERNAME:-smdg}"

log() { printf "\033[1;34m[%s]\033[0m %s\n" "$(date +%H:%M:%S)" "$*"; }
ok()  { printf "\033[1;32m✅ %s\033[0m\n" "$*"; }
err() { printf "\033[1;31m❌ %s\033[0m\n" "$*" >&2; }

# -----------------------------------------------------------------------------
# Автоопределение окружения
# -----------------------------------------------------------------------------
detect_target() {
    if [[ "${DEPLOY_TARGET}" != "auto" ]]; then
        echo "${DEPLOY_TARGET}"
        return
    fi

    if command -v kubectl >/dev/null 2>&1 && \
       kubectl cluster-info >/dev/null 2>&1; then
        echo "k8s"
        return
    fi
    if docker info 2>/dev/null | grep -q 'Swarm: active'; then
        echo "swarm"
        return
    fi
    echo "compose"
}

# -----------------------------------------------------------------------------
# Compose (standalone) — делегируем в основной скрипт
# -----------------------------------------------------------------------------
do_compose() {
    log "Docker Compose rolling update → ${NEW_TAG}"
    IMAGE_TAG="${NEW_TAG}" "${SCRIPT_DIR}/zero_downtime_deploy.sh"
}

# -----------------------------------------------------------------------------
# Swarm — используем штатный update_config
# -----------------------------------------------------------------------------
do_swarm() {
    local full_image="${DOCKER_USERNAME}/smdg:${NEW_TAG}"
    log "Docker Swarm rolling update: ${SERVICE_NAME} → ${full_image}"

    # Убедимся, что образ доступен всем нодам
    docker pull "${full_image}"

    # Миграции — разовый таск (swarm-mode service)
    log "Запуск one-shot миграций..."
    docker service create \
        --name "${STACK_NAME}_migrations_$(date +%s)" \
        --network "${STACK_NAME}_backend" \
        --restart-condition none \
        --replicas 1 \
        --detach=false \
        "${full_image}" \
        python /app/scripts/run_migrations_zero_downtime.py || {
            err "Migrations failed"
            return 1
        }

    log "Update service ${SERVICE_NAME}..."
    docker service update \
        --image "${full_image}" \
        --update-parallelism 1 \
        --update-delay 10s \
        --update-order start-first \
        --update-failure-action rollback \
        --update-monitor 60s \
        --update-max-failure-ratio 0 \
        --rollback-parallelism 1 \
        --rollback-delay 5s \
        --rollback-order start-first \
        --with-registry-auth \
        "${SERVICE_NAME}"

    log "Ожидаем завершения rollout..."
    # docker service ps с фильтром — проверка что нет Failed задач
    local attempts=0
    while (( attempts < 60 )); do
        if docker service ps "${SERVICE_NAME}" --format '{{.CurrentState}}' \
                | grep -vE '^(Running|Shutdown)' | grep -q .; then
            sleep 2
            attempts=$((attempts + 1))
        else
            ok "Swarm rolling update OK"
            return 0
        fi
    done

    err "Swarm update не завершился за 120s"
    docker service ps "${SERVICE_NAME}"
    return 1
}

# -----------------------------------------------------------------------------
# Kubernetes — штатный RollingUpdate через kubectl
# -----------------------------------------------------------------------------
do_k8s() {
    local full_image="${DOCKER_USERNAME}/smdg:${NEW_TAG}"
    log "Kubernetes rolling update: ${K8S_DEPLOYMENT}@${K8S_NAMESPACE} → ${full_image}"

    # Миграции как Job (ждём успех)
    log "Applying migration Job..."
    kubectl -n "${K8S_NAMESPACE}" delete job smdg-migrations --ignore-not-found
    kubectl -n "${K8S_NAMESPACE}" create job smdg-migrations \
        --image="${full_image}" \
        -- python /app/scripts/run_migrations_zero_downtime.py
    kubectl -n "${K8S_NAMESPACE}" wait --for=condition=complete \
        --timeout=300s job/smdg-migrations

    log "kubectl set image..."
    kubectl -n "${K8S_NAMESPACE}" set image \
        "deployment/${K8S_DEPLOYMENT}" \
        smdg="${full_image}" \
        --record=true

    log "Ожидаем rollout..."
    if kubectl -n "${K8S_NAMESPACE}" rollout status \
            "deployment/${K8S_DEPLOYMENT}" --timeout=300s; then
        ok "K8s rolling update OK"
    else
        err "Rollout не сошёлся → kubectl rollout undo"
        kubectl -n "${K8S_NAMESPACE}" rollout undo \
            "deployment/${K8S_DEPLOYMENT}"
        return 1
    fi
}

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
target=$(detect_target)
log "Target: ${target}  |  Tag: ${NEW_TAG}"

case "${target}" in
    compose) do_compose ;;
    swarm)   do_swarm ;;
    k8s)     do_k8s ;;
    *)
        err "Неизвестный target: ${target}"
        exit 2
        ;;
esac
