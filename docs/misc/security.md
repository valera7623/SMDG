# Безопасность

Политика безопасности SMDG.

## Сообщить об уязвимости

Пишите на **security@smdg.example**. Не создавайте публичные issues для нераскрытых уязвимостей.

В отчёте укажите:

- описание проблемы;
- шаги воспроизведения;
- версию SMDG (`GET /health`);
- желаемый срок раскрытия.

## Поддерживаемые версии

| Версия | Поддержка |
|--------|-----------|
| 4.x | Да |
| 3.x | Только security fixes |
| < 3.0 | Нет |

## Криптография

| Компонент | Технология |
|-----------|------------|
| Файлы | age (X25519) |
| Пароли | Argon2id |
| JWT | HS256 |
| 2FA | TOTP (RFC 6238) |
| TLS | Nginx, TLS 1.2+ |

## Секреты

- Docker Secrets в production (`secrets/`).
- `.env` не коммитится в git.
- Рекомендуется внешний secret manager (Vault, AWS SM).

## Чеклист hardening

- [ ] `DEV_MODE=false`
- [ ] Уникальный `JWT_SECRET_KEY` (≥64 байт)
- [ ] PostgreSQL с отдельной ролью
- [ ] Redis с паролем, только internal network
- [ ] Rate limiting включён
- [ ] Аудит отправляется off-host
- [ ] Регулярные бэкапы `encrypted/` и БД
- [ ] Ротация age-ключей (`python -m app.cli rotate-keys`)

## Аудит

Все изменяющие состояние операции пишутся в `audit_logs/`. Записи на английском, включают `user_id`, `tenant_id`, `action`, `resource_id`.

Подробнее: [src/SECURITY.md](../src/SECURITY.md), [locales/ru/SECURITY.md](../locales/ru/SECURITY.md).

## Compliance

Шаблон для ФЗ-152 / GDPR: [src/COMPLIANCE_TEMPLATE.md](../src/COMPLIANCE_TEMPLATE.md).
