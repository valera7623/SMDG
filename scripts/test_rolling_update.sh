#!/usr/bin/env bash
# =============================================================================
# scripts/test_rolling_update.sh
#
# Тест zero-downtime деплоя SMDG:
#   1. Запускаем непрерывный нагрузочный тест в фоне (curl в цикле).
#   2. Выполняем rolling-update.
#   3. Останавливаем нагрузку и собираем статистику.
#   4. PASS, если процент ошибок < ${MAX_ERROR_RATE_PERCENT} (default 0.5%).
#
# Usage:
#   ./scripts/test_rolling_update.sh
#   TARGET_URL=https://smdg.example.com/health/ready \
#     DEPLOY_CMD="IMAGE_TAG=4.0.1 ./scripts/zero_downtime_deploy.sh" \
#     MAX_ERROR_RATE_PERCENT=0.5 \
#     ./scripts/test_rolling_update.sh
# =============================================================================

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}/.."

TARGET_URL="${TARGET_URL:-http://localhost/health/ready}"
DEPLOY_CMD="${DEPLOY_CMD:-./scripts/zero_downtime_deploy.sh}"
REQUEST_INTERVAL="${REQUEST_INTERVAL:-0.1}"   # секунд между запросами
CONCURRENCY="${CONCURRENCY:-4}"               # параллельных воркеров
MAX_ERROR_RATE_PERCENT="${MAX_ERROR_RATE_PERCENT:-0.5}"
MAX_LATENCY_MS="${MAX_LATENCY_MS:-5000}"

TMP_DIR=$(mktemp -d -t smdg-zdt-XXXX)
LOAD_LOG="${TMP_DIR}/load.log"
STATS="${TMP_DIR}/stats.tsv"

echo "🧪 Zero-downtime тест"
echo "   URL:             ${TARGET_URL}"
echo "   Deploy cmd:      ${DEPLOY_CMD}"
echo "   Concurrency:     ${CONCURRENCY}"
echo "   Interval:        ${REQUEST_INTERVAL}s"
echo "   Max error rate:  ${MAX_ERROR_RATE_PERCENT}%"
echo "   Logs:            ${TMP_DIR}"
echo ""

# -----------------------------------------------------------------------------
# Нагрузка: N параллельных воркеров шлют GET, пишут статус+latency в лог.
# Формат строки: UNIX_TS\tSTATUS\tLATENCY_MS
# -----------------------------------------------------------------------------
worker() {
    local id="$1"
    while [[ -f "${TMP_DIR}/running" ]]; do
        local ts
        ts=$(date +%s)
        local start_ns
        start_ns=$(date +%s%N)
        local code
        # --max-time 5 гарантирует, что зависшее соединение не блокирует тест
        code=$(curl -s -o /dev/null --max-time 5 \
                    -w "%{http_code}" \
                    -k "${TARGET_URL}" || echo "000")
        local end_ns
        end_ns=$(date +%s%N)
        local latency_ms=$(( (end_ns - start_ns) / 1000000 ))
        printf "%s\t%s\t%s\n" "${ts}" "${code}" "${latency_ms}" >> "${STATS}"
        sleep "${REQUEST_INTERVAL}"
    done
}

cleanup() {
    rm -f "${TMP_DIR}/running" 2>/dev/null || true
    wait 2>/dev/null || true
}
trap cleanup EXIT

# -----------------------------------------------------------------------------
# Старт нагрузки
# -----------------------------------------------------------------------------
touch "${TMP_DIR}/running"
> "${STATS}"

echo "▶️  Стартуем нагрузку (${CONCURRENCY} воркеров)..."
for i in $(seq 1 "${CONCURRENCY}"); do
    worker "$i" &
done
LOAD_PIDS=($(jobs -p))

# Небольшой прогрев
sleep 3

pre_count=$(wc -l < "${STATS}")
pre_errors=$(awk -F'\t' '$2 != "200"' "${STATS}" | wc -l || true)
echo "  Baseline: ${pre_count} запросов, ${pre_errors} ошибок до деплоя"

# -----------------------------------------------------------------------------
# Деплой
# -----------------------------------------------------------------------------
echo ""
echo "🚀 Запускаем деплой: ${DEPLOY_CMD}"
DEPLOY_START=$(date +%s)
if eval "${DEPLOY_CMD}" | tee "${LOAD_LOG}"; then
    DEPLOY_STATUS=0
else
    DEPLOY_STATUS=$?
fi
DEPLOY_DURATION=$(( $(date +%s) - DEPLOY_START ))

# Дадим нагрузке поработать ещё чуть после деплоя
sleep 3

# -----------------------------------------------------------------------------
# Остановка нагрузки
# -----------------------------------------------------------------------------
echo ""
echo "🛑 Останавливаем нагрузку..."
rm -f "${TMP_DIR}/running"
for pid in "${LOAD_PIDS[@]}"; do
    wait "${pid}" 2>/dev/null || true
done

# -----------------------------------------------------------------------------
# Анализ
# -----------------------------------------------------------------------------
total=$(wc -l < "${STATS}")
ok=$(awk -F'\t' '$2 == "200"' "${STATS}" | wc -l)
errors=$(( total - ok ))

# Ошибки исключительно во время окна деплоя (берём всю длительность)
deploy_window_errors=$(awk -F'\t' -v start="${DEPLOY_START}" \
    '$1 >= start && $2 != "200" {c++} END {print c+0}' "${STATS}")

# p50 и p99 latency
sort -n -t$'\t' -k3 "${STATS}" -o "${STATS}.sorted"
p50_line=$(( total / 2 ))
p99_line=$(( total * 99 / 100 ))
p50=$(awk -F'\t' "NR == ${p50_line} { print \$3 }" "${STATS}.sorted" || echo 0)
p99=$(awk -F'\t' "NR == ${p99_line} { print \$3 }" "${STATS}.sorted" || echo 0)
max_lat=$(awk -F'\t' 'BEGIN{m=0} { if ($3+0>m) m=$3+0 } END { print m }' "${STATS}")

if (( total > 0 )); then
    error_rate=$(awk "BEGIN { printf \"%.2f\", ${errors} / ${total} * 100 }")
else
    error_rate="0.00"
fi

# Breakdown по статус-кодам
echo ""
echo "📊 Результаты:"
printf "   Всего запросов:     %d\n" "${total}"
printf "   Успешных (200):     %d\n" "${ok}"
printf "   Ошибок:             %d (%s%%)\n" "${errors}" "${error_rate}"
printf "   В окне деплоя:      %d\n" "${deploy_window_errors}"
printf "   Длительность дпл:   %ds\n" "${DEPLOY_DURATION}"
printf "   p50 / p99 / max:    %d / %d / %d ms\n" "${p50}" "${p99}" "${max_lat}"
echo ""
echo "   Распределение статусов:"
awk -F'\t' '{ c[$2]++ } END { for (k in c) printf "     %s: %d\n", k, c[k] }' "${STATS}" \
    | sort

# -----------------------------------------------------------------------------
# Вердикт
# -----------------------------------------------------------------------------
echo ""
if [[ "${DEPLOY_STATUS}" -ne 0 ]]; then
    echo "❌ Деплой вернул exit=${DEPLOY_STATUS}"
    exit "${DEPLOY_STATUS}"
fi

# awk-сравнение вещественных чисел
if awk "BEGIN { exit !(${error_rate} > ${MAX_ERROR_RATE_PERCENT}) }"; then
    echo "❌ FAIL: error rate ${error_rate}% > порога ${MAX_ERROR_RATE_PERCENT}%"
    echo "   Подробности: ${STATS}"
    exit 1
fi

if (( max_lat > MAX_LATENCY_MS )); then
    echo "❌ FAIL: max latency ${max_lat}ms > порога ${MAX_LATENCY_MS}ms"
    exit 1
fi

echo "✅ PASS: zero-downtime подтверждён"
echo "   (error rate ${error_rate}% ≤ ${MAX_ERROR_RATE_PERCENT}%, max ${max_lat}ms ≤ ${MAX_LATENCY_MS}ms)"
