#!/usr/bin/env bash
# =============================================================================
# Безопасная очистка Docker и связанных системных артефактов на Ubuntu.
#
# Удаляет: неиспользуемые образы, остановленные контейнеры, неиспользуемые
# volumes (с явным списком НИКОГДА не трогаемых томов), build cache,
# неиспользуемые сети; опционально apt cache и journal старше 30 дней.
#
# Использование:
#   ./scripts/docker-cleanup-ubuntu.sh              # с подтверждением
#   ./scripts/docker-cleanup-ubuntu.sh --force    # без вопросов
#   LOG_FILE=/tmp/cleanup.log ./scripts/docker-cleanup-ubuntu.sh --force
#
# Защищённые volumes (по умолчанию, имена как у docker compose project=smdg):
#   smdg_pgdata smdg_grafana_data smdg_minio_data smdg_smdg_keys
# Дополнить:  export SMDG_EXTRA_PROTECTED_VOLUMES="smdg_prometheus_data smdg_smdg_backups"
#
# Требования: docker (группа docker или root); для apt/journal — root или sudo.
# =============================================================================

set -Eeuo pipefail

SCRIPT_PATH="${BASH_SOURCE[0]}"
SCRIPT_DIR="$(cd "$(dirname "${SCRIPT_PATH}")" && pwd)"
LOG_FILE="${LOG_FILE:-${SCRIPT_DIR}/../logs/docker-cleanup-$(date +%Y%m%d).log}"
mkdir -p "$(dirname "${LOG_FILE}")" 2>/dev/null || LOG_FILE="/tmp/smdg-docker-cleanup.log"

# --- colors ---
if [[ -t 1 ]] && command -v tput >/dev/null 2>&1; then
  readonly C_GREEN="$(tput setaf 2)"
  readonly C_YELLOW="$(tput setaf 3)"
  readonly C_RED="$(tput setaf 1)"
  readonly C_BOLD="$(tput bold)"
  readonly C_RESET="$(tput sgr0)"
else
  readonly C_GREEN="" C_YELLOW="" C_RED="" C_BOLD="" C_RESET=""
fi

FORCE=0

usage() {
  sed -n '1,25p' "$SCRIPT_PATH" | sed -e 's/^# \{0,1\}//'
  echo ""
  echo "Options:"
  echo "  --force     Не спрашивать подтверждение"
  echo "  -h, --help  Справка"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --force) FORCE=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

ts() { date '+%Y-%m-%d %H:%M:%S %z'; }

# Пишем в лог без цветов; на терминал — с цветами при необходимости
log_line() {
  echo "[$(ts)] $*" | tee -a "${LOG_FILE}" >/dev/null
}

msg_ok()    { echo "${C_GREEN}${C_BOLD}✓${C_RESET} ${C_GREEN}$*${C_RESET}"; log_line "OK: $*"; }
msg_warn()  { echo "${C_YELLOW}${C_BOLD}!${C_RESET} ${C_YELLOW}$*${C_RESET}"; log_line "WARN: $*"; }
msg_err()   { echo "${C_RED}${C_BOLD}✗${C_RESET} ${C_RED}$*${C_RESET}" >&2; log_line "ERR: $*"; }

require_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    msg_err "docker не найден в PATH"
    exit 1
  fi
  if ! docker info >/dev/null 2>&1; then
    msg_err "Нет доступа к Docker (запустите от пользователя в группе docker или с sudo)"
    exit 1
  fi
}

# Доступное место на указанном mountpoint (KiB)
disk_avail_kib() {
  local mp="${1:-/}"
  df -Pk "${mp}" 2>/dev/null | awk -v m="${mp}" 'NR==2 {print $4+0}'
}

disk_df_line() {
  local mp="${1:-/}"
  df -hP "${mp}" 2>/dev/null | tail -n 1
}

print_disk_table() {
  local label="$1"
  local mp="${2:-/}"
  echo ""
  echo "${C_BOLD}══ ${label} (${mp}) ══${C_RESET}"
  printf "${C_BOLD}%-18s %8s %8s %8s %6s${C_RESET}\n" "Filesystem" "Size" "Used" "Avail" "Use%"
  df -hP "${mp}" 2>/dev/null | tail -n +2 | while read -r fs size used avail pct rest; do
    printf "%-18s %8s %8s %8s %6s\n" "$fs" "$size" "$used" "$avail" "$pct"
  done
  local kib
  kib="$(disk_avail_kib "${mp}")"
  echo "  Доступно (df -Pk, KiB): ${kib}"
}

bytes_human() {
  local b="${1:-0}"
  if [[ "${b}" -ge 1073741824 ]]; then
    awk "BEGIN{printf \"%.2f GiB\", ${b}/1073741824}"
  elif [[ "${b}" -ge 1048576 ]]; then
    awk "BEGIN{printf \"%.2f MiB\", ${b}/1048576}"
  else
    printf '%s B' "${b}"
  fi
}

# ---------------------------------------------------------------------------
# Защищённые volumes: явный список + дополнение из env
# ---------------------------------------------------------------------------
declare -a PROTECTED_VOLUMES=(
  smdg_pgdata
  smdg_grafana_data
  smdg_minio_data
  smdg_smdg_keys
)

if [[ -n "${SMDG_EXTRA_PROTECTED_VOLUMES:-}" ]]; then
  # shellcheck disable=SC2206
  extra=( ${SMDG_EXTRA_PROTECTED_VOLUMES} )
  PROTECTED_VOLUMES+=("${extra[@]}")
fi

is_protected_volume() {
  local v="$1"
  local p
  for p in "${PROTECTED_VOLUMES[@]}"; do
    [[ "${v}" == "${p}" ]] && return 0
  done
  return 1
}

run_sudo() {
  if [[ "${EUID:-0}" -eq 0 ]]; then
    "$@"
  elif command -v sudo >/dev/null 2>&1; then
    sudo -n "$@" 2>/dev/null || sudo "$@"
  else
    return 1
  fi
}

# ---------------------------------------------------------------------------
# Подтверждение
# ---------------------------------------------------------------------------
confirm_or_exit() {
  [[ "${FORCE}" -eq 1 ]] && return 0
  echo ""
  msg_warn "Будут выполнены агрессивные операции очистки Docker и системы."
  echo "Защищённые volumes не удаляются даже если «висят»: ${PROTECTED_VOLUMES[*]}"
  read -r -p "Продолжить? [y/N] " ans
  case "${ans}" in
    y|Y|yes|YES) return 0 ;;
    *) msg_err "Отменено пользователем."; exit 3 ;;
  esac
}

# ---------------------------------------------------------------------------
# Основная логика
# ---------------------------------------------------------------------------
main() {
  log_line "======== session start ========"
  require_docker

  local mount_point="/"
  local before_avail after_avail
  before_avail="$(disk_avail_kib "${mount_point}")"
  before_avail="${before_avail:-0}"

  print_disk_table "Диск ДО очистки" "${mount_point}"

  confirm_or_exit

  msg_ok "Остановленные контейнеры: prune"
  docker container prune -f >>"${LOG_FILE}" 2>&1 || true

  msg_ok "Dangling-образы и затем все неиспользуемые образы: prune"
  docker image prune -f >>"${LOG_FILE}" 2>&1 || true
  docker image prune -a -f >>"${LOG_FILE}" 2>&1 || true

  msg_ok "Build cache (BuildKit / builder): prune"
  if ! docker builder prune -af >>"${LOG_FILE}" 2>&1; then
    msg_warn "docker builder prune недоступен или ошибка — пропуск (проверьте buildx)"
  fi

  msg_ok "Неиспользуемые сети: prune"
  docker network prune -f >>"${LOG_FILE}" 2>&1 || true

  msg_ok "Неиспользуемые volumes (явная защита имён, без docker volume prune)"
  local vol
  while IFS= read -r vol; do
    [[ -z "${vol}" ]] && continue
    if is_protected_volume "${vol}"; then
      msg_warn "volume защищён, пропуск: ${vol}"
      log_line "SKIP protected volume: ${vol}"
      continue
    fi
    local using
    using="$(docker ps -aq --filter volume="${vol}" 2>/dev/null | wc -l | tr -d ' ')"
    if [[ "${using}" != "0" ]]; then
      log_line "SKIP volume in use (${using} ctr): ${vol}"
      continue
    fi
    if docker volume rm "${vol}" >>"${LOG_FILE}" 2>&1; then
      msg_ok "удалён неиспользуемый volume: ${vol}"
    else
      log_line "volume rm не выполнен (занят/гонка): ${vol}"
    fi
  done < <(docker volume ls -q)

  if run_sudo apt-get clean 2>&1 | tee -a "${LOG_FILE}"; then
    msg_ok "apt: clean"
  else
    msg_warn "apt clean пропущен (нужен root/sudo)"
  fi

  if run_sudo apt-get autoclean -y 2>&1 | tee -a "${LOG_FILE}"; then
    msg_ok "apt: autoclean"
  else
    msg_warn "apt autoclean пропущен"
  fi

  if run_sudo journalctl --vacuum-time=30d 2>&1 | tee -a "${LOG_FILE}"; then
    msg_ok "journald: vacuum старше 30 дней"
  else
    msg_warn "journalctl vacuum пропущен (нужен root/sudo)"
  fi

  after_avail="$(disk_avail_kib "${mount_point}")"
  after_avail="${after_avail:-0}"
  local freed
  freed=$((after_avail - before_avail))
  [[ "${freed}" -lt 0 ]] && freed=0

  print_disk_table "Диск ПОСЛЕ очистки" "${mount_point}"

  echo ""
  echo "${C_BOLD}── Сводка ──${C_RESET}"
  printf "  Доступно до:     %12s KiB\n" "${before_avail}"
  printf "  Доступно после:  %12s KiB\n" "${after_avail}"
  printf "  ${C_GREEN}Освобождено (оценка по df): ~%s${C_RESET}\n" "$(bytes_human $((freed * 1024)))"
  msg_ok "Лог: ${LOG_FILE}"
  log_line "======== session end freed_kib_estimate=${freed} ========"
}

main "$@"
