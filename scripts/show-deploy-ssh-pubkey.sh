#!/usr/bin/env bash
# Печатает публичный ключ для GitHub Secret VPS_SSH_KEY (добавить на второй VPS).
#
# Usage:
#   ./scripts/show-deploy-ssh-pubkey.sh path/to/private_key
#   ./scripts/show-deploy-ssh-pubkey.sh   # reads ~/.ssh/id_rsa

set -euo pipefail

KEY="${1:-$HOME/.ssh/id_rsa}"
if [[ ! -f "$KEY" ]]; then
  echo "Private key not found: $KEY" >&2
  exit 1
fi
chmod 600 "$KEY" 2>/dev/null || true
echo "Public key (one line for authorized_keys):"
ssh-keygen -y -f "$KEY"
echo ""
echo "Fingerprint:"
ssh-keygen -lf "$KEY"
