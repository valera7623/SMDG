# Инцидент: Проблемы аутентификации

## Симптомы

- всплеск 401/403
- жалобы на невозможность входа

## Диагностика

```bash
docker compose logs --since 30m smdg | grep -Ei "auth|401|403|invalid credentials|token" | tail -200
curl -s -X POST http://localhost:8000/api/auth/login -H "Content-Type: application/x-www-form-urlencoded" -d "username=admin&password=admin" -i
```

## Восстановление

1. Проверить корректность `JWT_SECRET`, время системы, cookie policy.
2. Проверить состояние пользователя (active/role/tenant).
3. Проверить Redis/БД доступность для auth flow.
4. При массовом сбое включить инцидентную коммуникацию для пользователей.
