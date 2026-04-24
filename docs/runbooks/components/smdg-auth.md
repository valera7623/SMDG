# SMDG Auth Runbook

## Назначение

JWT/cookie auth, 2FA, управление пользователями и контроль tenant-доступа.

## Проверки

```bash
curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=admin" -i
docker compose logs --since 30m smdg | grep -Ei "auth|401|429|rate limit" | tail -50
```

## Диагностика проблем

- массовые 401 -> проверить валидность паролей, JWT secret, clock skew
- массовые 429 -> проверить rate limit и поведение клиентов
- проблемы 2FA -> проверить TOTP поток и состояние пользователя

## Связанные runbooks

- `incidents/auth-failure.md`
- `incidents/rate-limiting.md`
