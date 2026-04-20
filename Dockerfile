FROM python:3.10

ARG DEPLOYMENT_TYPE=single
ENV DEPLOYMENT_TYPE=${DEPLOYMENT_TYPE}

WORKDIR /app

# Устанавливаем минимально необходимое + curl для healthcheck
RUN apt-get update && apt-get install -y \
    age \
    libmagic1 \
    netcat-openbsd \
    postgresql-client \
    redis-tools \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml poetry.lock ./
RUN pip install --no-cache-dir poetry && \
    poetry config virtualenvs.create false && \
    poetry install --no-interaction --no-ansi --only main --no-root

RUN pip install --no-cache-dir "setuptools<81"

COPY . .

# Шаблон окружения под выбранный профиль (docker build --build-arg DEPLOYMENT_TYPE=russia)
RUN set -eux; \
    if [ -f ".env.${DEPLOYMENT_TYPE}.example" ]; then \
      cp ".env.${DEPLOYMENT_TYPE}.example" /app/.env; \
    elif [ -f ".env.single.example" ]; then \
      cp ".env.single.example" /app/.env; \
    fi

# Создаём директории для данных
RUN mkdir -p /app/uploads /app/encrypted /app/decrypted /app/keys /app/certs /app/scripts

# Делаем скрипты исполняемыми
RUN chmod +x /app/entrypoint.sh /app/scripts/*.sh 2>/dev/null || true
RUN chmod +x /app/scripts/*.py 2>/dev/null || true

COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
CMD []   