FROM python:3.10-slim

WORKDIR /app

# Устанавливаем минимально необходимое + curl для healthcheck
RUN apt-get update && apt-get install -y \
    age \
    libmagic1 \
    netcat-openbsd \
    postgresql-client \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/uploads /app/encrypted /app/decrypted /app/keys /app/certs

COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
CMD []   