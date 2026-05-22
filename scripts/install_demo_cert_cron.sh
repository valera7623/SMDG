#!/usr/bin/env bash
# Install a daily cron job to renew demo TLS certificates.
#
# Usage:
#   ./scripts/install_demo_cert_cron.sh
#   ./scripts/install_demo_cert_cron.sh --uninstall
#
# Default schedule: 03:17 daily (offset from top of hour to reduce LE load spikes).

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_FILE="${LOG_FILE:-${ROOT_DIR}/logs/cert-renew.log}"
CRON_SCHEDULE="${CRON_SCHEDULE:-17 3 * * *}"
MARKER="renew_demo_tls.sh"

usage() {
  echo "Usage: $0 [--uninstall]"
  echo "  Installs cron: ${CRON_SCHEDULE} cd ${ROOT_DIR} && ./scripts/renew_demo_tls.sh"
  echo "  Log file: ${LOG_FILE}"
}

uninstall=false
for arg in "$@"; do
  case "${arg}" in
    --uninstall) uninstall=true ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: ${arg}" >&2; usage; exit 1 ;;
  esac
done

mkdir -p "$(dirname "${LOG_FILE}")"

if [ "${uninstall}" = true ]; then
  if crontab -l 2>/dev/null | grep -q "${MARKER}"; then
    crontab -l 2>/dev/null | grep -v "${MARKER}" | crontab -
    echo "Removed cron job for ${MARKER}"
  else
    echo "No cron job found for ${MARKER}"
  fi
  exit 0
fi

CRON_LINE="${CRON_SCHEDULE} cd ${ROOT_DIR} && ${ROOT_DIR}/scripts/renew_demo_tls.sh >> ${LOG_FILE} 2>&1 # ${MARKER}"

if crontab -l 2>/dev/null | grep -q "${MARKER}"; then
  crontab -l 2>/dev/null | grep -v "${MARKER}" | crontab -
fi

(crontab -l 2>/dev/null; echo "${CRON_LINE}") | crontab -

echo "Installed cron job:"
echo "  ${CRON_LINE}"
echo ""
echo "Verify: crontab -l"
echo "Test run: ${ROOT_DIR}/scripts/renew_demo_tls.sh"
