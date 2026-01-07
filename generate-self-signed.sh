#!/bin/bash
mkdir -p certs
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
    -keyout certs/privkey.pem \
    -out certs/fullchain.pem \
    -subj "/C=RU/ST=Moscow/L=Moscow/O=SMDG/OU=IT/CN=localhost"
echo "Самоподписанные сертификаты созданы в ./certs/"