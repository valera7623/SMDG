#!/bin/sh
# Certbot deploy hook — runs inside the certbot container on successful renew.
# /etc/letsencrypt is ./certs on the host (shared with nginx).
#
# Updates nginx-facing symlinks after renewal. Host script renew_demo_tls.sh
# reloads nginx afterward (certbot cannot reload nginx from this container).

set -eu

if [ -z "${RENEWED_LINEAGE:-}" ]; then
  exit 0
fi

ln -sf "${RENEWED_LINEAGE}/fullchain.pem" /etc/letsencrypt/fullchain.pem
ln -sf "${RENEWED_LINEAGE}/privkey.pem" /etc/letsencrypt/privkey.pem

echo "Deploy hook: linked nginx certs to ${RENEWED_LINEAGE}"
