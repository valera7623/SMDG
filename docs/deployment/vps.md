# VPS

Развёртывание SMDG на VPS.

## Требования

| Ресурс | Минимум | Рекомендуется |
|--------|---------|---------------|
| CPU | 2 ядра | 4+ |
| RAM | 4 ГБ | 8+ ГБ |
| Диск | 20 ГБ SSD | 50+ ГБ |
| ОС | Ubuntu 22.04 / 24.04 | Ubuntu 24.04 LTS |

## Подготовка сервера

```bash
# Docker + Compose
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER

# Клонирование
git clone https://github.com/valera7623/SMDG.git /opt/smdg
cd /opt/smdg
```

## Конфигурация

```bash
cp .env.example .env
# Отредактируйте DOMAIN, LETSENCRYPT_EMAIL, DEPLOYMENT_TYPE
mkdir -p secrets
# Создайте secret-файлы (см. admin-guide/deployment.md)
```

## TLS (Let's Encrypt)

В production compose certbot обновляет сертификаты автоматически.

Ручное обновление:

```bash
./scripts/renew_tls_certificates.sh
```

## Деплой

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

Zero-downtime:

```bash
./scripts/zero_downtime_deploy.sh
```

## Известные VPS

| Сервер | IP | Профиль | Workflow |
|--------|-----|---------|----------|
| primary | 186.246.3.65 | production | `deploy-primary.yml` |
| fileguardian | 74.208.252.225 | demo | `deploy-fileguardian.yml` |

## Документация на VPS

Статический MkDocs-сайт (`site/`) можно отдавать через Nginx:

```nginx
location /help/ {
    alias /opt/smdg/site/;
    try_files $uri $uri/ /help/index.html;
}
```

Сборка: `poetry run mkdocs build`

## Smoke-тест

```bash
BASE_URL=https://your-domain.com ./scripts/post-deploy-verify.sh
```
