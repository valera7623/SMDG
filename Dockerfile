FROM python:3.10-slim AS builder

ARG DEPLOYMENT_TYPE=single
ENV DEPLOYMENT_TYPE=${DEPLOYMENT_TYPE}
ENV PIP_NO_CACHE_DIR=1
ENV DEBIAN_FRONTEND=noninteractive

WORKDIR /app

RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Compression support for FastAPI middleware (Brotli)
RUN pip install --no-cache-dir brotli

COPY pyproject.toml poetry.lock ./
RUN pip install --no-cache-dir "poetry==1.8.2" && \
    poetry config virtualenvs.create false && \
    poetry install --no-interaction --no-ansi --only main --no-root && \
    pip install --no-cache-dir "setuptools>=82,<83"
# Jinja2 — обязательна для app/templates (главная /). Явно, чтобы старые кэши слоёв не дали пустой образ без jinja2.
RUN pip install --no-cache-dir "jinja2>=3.1.6" "MarkupSafe>=2.0"
# setuptools<82 vendors wheel<0.46.2 under _vendor/ (Trivy). poetry + older setuptools can also duplicate top-level wheel-*.dist-info; keep one.
RUN pip install --no-cache-dir --upgrade "wheel>=0.46.2" && \
    python3 -c 'import pathlib, shutil; from packaging.version import Version; sp=pathlib.Path("/usr/local/lib/python3.10/site-packages"); ds=sorted(sp.glob("wheel-*.dist-info"), key=lambda p: Version(p.stem.split("-", 1)[1])); [shutil.rmtree(d) for d in ds[:-1]] if len(ds) > 1 else None' && \
    test "$(find /usr/local/lib/python3.10/site-packages -maxdepth 1 -name 'wheel-*.dist-info' | wc -l)" -eq 1
# Stale wheel-0.45.1 metadata after setuptools upgrade; virtualenv seeds an old wheel (Trivy). Poetry is not needed in the final site tree.
RUN rm -rf /usr/local/lib/python3.10/site-packages/setuptools/_vendor/wheel-0.45.1.dist-info && \
    pip uninstall -y poetry virtualenv 2>/dev/null || true

FROM python:3.10-slim AS runtime

ARG DEPLOYMENT_TYPE=single
ENV DEPLOYMENT_TYPE=${DEPLOYMENT_TYPE}
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DEBIAN_FRONTEND=noninteractive

WORKDIR /app

RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends \
    age \
    gosu \
    libmagic1 \
    netcat-openbsd \
    postgresql-client \
    redis-tools \
    curl \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Keep runtime image self-sufficient for Brotli imports
RUN pip install --no-cache-dir brotli

RUN groupadd --gid 1000 smdg && \
    useradd --uid 1000 --gid smdg --shell /usr/sbin/nologin --create-home smdg

COPY --from=builder /usr/local/lib/python3.10 /usr/local/lib/python3.10
COPY --from=builder /usr/local/bin /usr/local/bin
# Re-apply: cached COPY can leave duplicate top-level wheel-*.dist-info; remove stale setuptools vendor metadata and build tools.
RUN pip install --no-cache-dir --force-reinstall "setuptools>=82,<83" && \
    pip install --no-cache-dir --upgrade "wheel>=0.46.2" && \
    python3 -c 'import pathlib, shutil; from packaging.version import Version; sp=pathlib.Path("/usr/local/lib/python3.10/site-packages"); \
ds=sorted(sp.glob("setuptools-*.dist-info"), key=lambda p: Version(p.name[len("setuptools-"):-len(".dist-info")])); [shutil.rmtree(d) for d in ds[:-1]] if len(ds) > 1 else None; \
ds=sorted(sp.glob("wheel-*.dist-info"), key=lambda p: Version(p.stem.split("-", 1)[1])); [shutil.rmtree(d) for d in ds[:-1]] if len(ds) > 1 else None' && \
    test "$(find /usr/local/lib/python3.10/site-packages -maxdepth 1 -name 'setuptools-*.dist-info' | wc -l)" -eq 1 && \
    test "$(find /usr/local/lib/python3.10/site-packages -maxdepth 1 -name 'wheel-*.dist-info' | wc -l)" -eq 1 && \
    rm -rf /usr/local/lib/python3.10/site-packages/setuptools/_vendor/wheel-0.45.1.dist-info && \
    rm -rf /usr/local/lib/python3.10/site-packages/setuptools/_vendor/jaraco.context-5.3.0.dist-info && \
    pip uninstall -y poetry poetry-core virtualenv 2>/dev/null || true
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
