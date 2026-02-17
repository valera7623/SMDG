#!/bin/bash
set -e

CERT_DIR="/certs"
mkdir -p "$CERT_DIR"

if [ ! -f "$CERT_DIR/localhost.pem" ]; then
    echo "Генерируем self-signed сертификат для localhost..."
    openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
        -keyout "$CERT_DIR/localhost-key.pem" \
        -out "$CERT_DIR/localhost.pem" \
        -subj "/C=NL/ST=Limburg/L=Kerkrade/O=SMDG/CN=localhost" \
        -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"
    
    chmod 644 "$CERT_DIR/localhost.pem"
    chmod 600 "$CERT_DIR/localhost-key.pem"
    echo "Сертификат создан: $CERT_DIR/localhost.pem"
else
    echo "Сертификат уже существует: $CERT_DIR/localhost.pem"
fi