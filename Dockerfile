FROM python:3.10-slim AS builder

ARG DEPLOYMENT_TYPE=single
ENV DEPLOYMENT_TYPE=${DEPLOYMENT_TYPE}
ENV PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Compression support for FastAPI middleware (Brotli)
RUN pip install --no-cache-dir brotli

COPY pyproject.toml poetry.lock ./
RUN pip install --no-cache-dir poetry && \
    poetry config virtualenvs.create false && \
    poetry install --no-interaction --no-ansi --only main --no-root && \
    pip install --no-cache-dir "setuptools<81"
# Jinja2 — обязательна для app/templates (главная /). Явно, чтобы старые кэши слоёв не дали пустой образ без jinja2.
RUN pip install --no-cache-dir "jinja2>=3.1.6" "MarkupSafe>=2.0"


FROM python:3.10-slim AS runtime

ARG DEPLOYMENT_TYPE=single
ENV DEPLOYMENT_TYPE=${DEPLOYMENT_TYPE}
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    age \
    gosu \
    libmagic1 \
    netcat-openbsd \
    postgresql-client \
    redis-tools \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Keep runtime image self-sufficient for Brotli imports
RUN pip install --no-cache-dir brotli

RUN groupadd --gid 10001 smdg && \
    useradd --uid 10001 --gid smdg --shell /usr/sbin/nologin --create-home smdg

COPY --from=builder /usr/local/lib/python3.10 /usr/local/lib/python3.10
COPY --from=builder /usr/local/bin /usr/local/bin
COPY . .

RUN set -eux; \
    if [ -f ".env.${DEPLOYMENT_TYPE}.example" ]; then \
      cp ".env.${DEPLOYMENT_TYPE}.example" /app/.env; \
    elif [ -f ".env.single.example" ]; then \
      cp ".env.single.example" /app/.env; \
    fi

RUN mkdir -p /app/uploads /app/encrypted /app/decrypted /app/keys /app/certs /app/scripts && \
    chmod +x /app/entrypoint.sh /app/scripts/*.sh 2>/dev/null || true && \
    chmod +x /app/scripts/*.py 2>/dev/null || true && \
    chown -R smdg:smdg /app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD curl -fsS http://localhost:8000/health/live || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
CMD []
