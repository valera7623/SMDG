# API — authentication

## Login

```http
POST /api/auth/login
Content-Type: application/x-www-form-urlencoded

username=admin&password=secret
```

On success a cookie is set:

```http
Set-Cookie: access_token=<JWT>; HttpOnly; Secure; SameSite=Lax; Path=/
```

| Parameter | Value |
|-----------|-------|
| Algorithm | HS256 |
| TTL | 60 min (`JWT_ACCESS_EXPIRES_MINUTES`) |
| HttpOnly | Yes |
| Secure | Yes (production) |

## 2FA

If 2FA is enabled, a TOTP code is required after the password:

```http
POST /api/auth/verify-2fa
```

Setup: `POST /api/auth/setup-2fa`, `POST /api/auth/verify-2fa-setup`.

## Bearer token

```http
GET /api/files
Authorization: Bearer <jwt_token>
```

## Registration

```http
POST /api/auth/register
Content-Type: application/json

{"email": "user@example.com", "password": "...", "role": "user"}
```

Rate limit: `RATE_LIMIT_REGISTER` (default `10/minute`, `3/hour` in demo).

## Logout

```http
POST /api/auth/logout
```

## Change password

```http
POST /api/auth/change-password
```

Requires authentication. Rate limit: `5/minute`.

## Roles

| Role | Description |
|------|-------------|
| `user` | Basic user |
| `doctor` | Extended access |
| `admin` | Tenant administrator |
| `super_admin` | Cross-tenant (`saas`) |
