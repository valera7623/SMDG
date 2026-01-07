# Dockerfile
FROM python:3.10-slim

WORKDIR /app

# Устанавливаем age для шифрования
RUN apt-get update && apt-get install -y age && apt-get clean

# Копируем зависимости и устанавливаем их
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код
COPY . .

# Создаём директории для сертификатов
RUN mkdir -p /app/certs

EXPOSE 8000

# Запуск с поддержкой HTTPS
# Варианты:
# 1. Самоподписанный сертификат (для теста)
# 2. Реальные сертификаты (положите в ./certs/fullchain.pem и privkey.pem)
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--ssl-keyfile", "/app/certs/privkey.pem", \
     "--ssl-certfile", "/app/certs/fullchain.pem"]