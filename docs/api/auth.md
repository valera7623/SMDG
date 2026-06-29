# API — аутентификация

## Вход

```http
POST /api/auth/login
Content-Type: application/x-www-form-urlencoded

username=admin&password=secret
```

При успехе устанавливается cookie:

```http
Set-Cookie: access_token=<JWT>; HttpOnly; Secure; SameSite=Lax; Path=/
```

| Параметр | Значение |
|----------|----------|
| Алгоритм | HS256 |
| TTL | 60 мин (`JWT_ACCESS_EXPIRES_MINUTES`) |
| HttpOnly | Да |
| Secure | Да (production) |

## 2FA

Если 2FA включена, после пароля требуется TOTP-код:

```http
POST /api/auth/verify-2fa
```

Настройка: `POST /api/auth/setup-2fa`, `POST /api/auth/verify-2fa-setup`.

## Bearer Token

```http
GET /api/files
Authorization: Bearer <jwt_token>
```

## Регистрация

```http
POST /api/auth/register
Content-Type: application/json

{"email": "user@example.com", "password": "...", "role": "user"}
```

Rate limit: `RATE_LIMIT_REGISTER` (по умолчанию `10/minute`, в demo `3/hour`).

## Выход

```http
POST /api/auth/logout
```

## Смена пароля

```http
POST /api/auth/change-password
```

Требует аутентификации. Rate limit: `5/minute`.

## Роли

| Роль | Описание |
|------|----------|
| `user` | Базовый пользователь |
| `doctor` | Расширенный доступ |
| `admin` | Администратор tenant |
| `super_admin` | Кросс-tenant (`saas`) |
