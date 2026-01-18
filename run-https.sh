#!/usr/bin/env bash
uvicorn app.main:app --reload \
  --host 0.0.0.0 \
  --port 8000 \
  --ssl-keyfile=certs/localhost+1-key.pem \
  --ssl-certfile=certs/localhost+1.pem