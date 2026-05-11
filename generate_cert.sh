#!/bin/bash
set -euo pipefail

CERT_DIR="${CERT_DIR:-./certs}"
mkdir -p "$CERT_DIR"

CERT_FILE="$CERT_DIR/fullchain.pem"
KEY_FILE="$CERT_DIR/privkey.pem"
LOCALHOST_CERT="$CERT_DIR/localhost.pem"
LOCALHOST_KEY="$CERT_DIR/localhost-key.pem"

if [ ! -f "$CERT_FILE" ] || [ ! -f "$KEY_FILE" ]; then
    echo "Генерируем self-signed сертификат для localhost..."
    openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
        -keyout "$KEY_FILE" \
        -out "$CERT_FILE" \
        -subj "/C=NL/ST=Limburg/L=Kerkrade/O=SMDG/CN=localhost" \
        -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"
    
    chmod 644 "$CERT_FILE"
    chmod 600 "$KEY_FILE"
    echo "Сертификат создан: $CERT_FILE"
else
    echo "Сертификат уже существует: $CERT_FILE"
fi

# Backward-compatible filenames for older local nginx snippets.
if [ ! -f "$LOCALHOST_CERT" ]; then
    cp "$CERT_FILE" "$LOCALHOST_CERT"
    chmod 644 "$LOCALHOST_CERT"
fi
if [ ! -f "$LOCALHOST_KEY" ]; then
    cp "$KEY_FILE" "$LOCALHOST_KEY"
    chmod 600 "$LOCALHOST_KEY"
fi