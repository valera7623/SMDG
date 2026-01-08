FROM python:3.10-slim

WORKDIR /app

RUN apt-get update && apt-get install -y age libmagic1 && apt-get clean

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/uploads /app/encrypted /app/decrypted /app/keys /app/certs

EXPOSE 8000

# Если main.py в папке app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

     
     # Уберите SSL параметры если нет сертификатов
     # "--ssl-keyfile", "/app/certs/privkey.pem", \
     # "--ssl-certfile", "/app/certs/fullchain.pem"]