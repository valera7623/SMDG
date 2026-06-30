#!/usr/bin/env bash
# Certbot stores live/archive as root:root 700. Docker BuildKit still walks the
# repo tree for context and fails with "permission denied" on unreadable dirs
# even when certs/ is listed in .dockerignore.
#
# Usage (on VPS after certbot / before docker compose build):
#   ./scripts/fix_docker_build_permissions.sh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CERTS_DIR="${CERTS_DIR:-${ROOT_DIR}/certs}"

fix_dir() {
  local dir="$1"
  [ -d "${dir}" ] || return 0
  if [ -r "${dir}" ] && [ -x "${dir}" ]; then
    return 0
  fi
  echo "Fixing traverse permissions: ${dir}"
  if chmod u+rx,go+rx "${dir}" 2>/dev/null; then
    return 0
  fi
  sudo chmod u+rx,go+rx "${dir}"
}

for sub in archive live accounts; do
  fix_dir "${CERTS_DIR}/${sub}"
done

echo "Docker build context permissions OK under ${CERTS_DIR}"
