FROM python:3.10-slim

WORKDIR /app

RUN apt-get update && apt-get install -y age libmagic1 && apt-get clean

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/uploads /app/encrypted /app/decrypted /app/keys /app/certs

EXPOSE 8000


COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

ENTRYPOINT ["/app/entrypoint.sh"]
CMD []    