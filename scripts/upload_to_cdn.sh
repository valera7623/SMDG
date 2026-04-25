#!/bin/bash
# Sync static/ to S3 + CloudFront invalidation. Настройте окружение: S3_BUCKET, CLOUDFRONT_ID, AWS_REGION.
set -euo pipefail

ASSETS_DIR="${ASSETS_DIR:-static}"
S3_BUCKET="${S3_BUCKET:-smdg-cdn}"
CLOUDFRONT_ID="${CLOUDFRONT_ID:-}"
AWS_REGION="${AWS_REGION:-us-east-1}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "Uploading to s3://${S3_BUCKET}/static/ ..."

if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PY="$ROOT/.venv/bin/python"
elif command -v poetry &>/dev/null; then
  PY="poetry run python"
else
  PY="python3"
fi

echo "Generating asset manifest..."
$PY scripts/generate_asset_manifest.py "$ASSETS_DIR"

# Долгий кэш для fingerprint-имён (CSS/JS/шрифты/картинки); без HTML и без сырого manifest в sync
aws s3 sync "$ASSETS_DIR" "s3://${S3_BUCKET}/static/" \
  --region "$AWS_REGION" \
  --delete \
  --cache-control "public, max-age=31536000, immutable" \
  --exclude "*.html" \
  --exclude "manifest.json"

echo "Uploading HTML (no cache)..."
aws s3 sync "$ASSETS_DIR" "s3://${S3_BUCKET}/static/" \
  --region "$AWS_REGION" \
  --cache-control "no-cache, no-store, must-revalidate" \
  --exclude "*" \
  --include "*.html"

if [[ -f "$ASSETS_DIR/manifest.json" ]]; then
  aws s3 cp "$ASSETS_DIR/manifest.json" "s3://${S3_BUCKET}/static/manifest.json" \
    --region "$AWS_REGION" \
    --cache-control "public, max-age=300" \
    --content-type "application/json"
fi

if [[ -n "$CLOUDFRONT_ID" ]]; then
  echo "CloudFront invalidation..."
  INVALIDATION_ID=$(aws cloudfront create-invalidation \
    --distribution-id "$CLOUDFRONT_ID" \
    --paths "/*" \
    --query 'Invalidation.Id' \
    --output text)
  echo "Invalidation ID: $INVALIDATION_ID"
  aws cloudfront wait invalidation-completed \
    --distribution-id "$CLOUDFRONT_ID" \
    --id "$INVALIDATION_ID"
  echo "Done."
  if [[ -n "${CLOUDFRONT_DOMAIN:-}" ]]; then
    echo "CDN: https://${CLOUDFRONT_DOMAIN}/static/"
  fi
else
  echo "CLOUDFRONT_ID not set — skip invalidation."
fi
