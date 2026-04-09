# TESTING.md

**Дата:** 06 апреля 2026  
**Версия SMDG:** 1.0  
**Цель документа:** Полное описание стратегии тестирования Secure Medical Data Gateway с акцентом на безопасность, шифрование и соответствие медицинским требованиям (ФЗ-152).

---

## 1. Введение

SMDG — критически важная система обработки медицинских данных.  
**Требования к QA:**
- Полное покрытие шифрования (age)
- Интеграционные тесты ClamAV
- Полноценное тестирование 2FA/TOTP
- Coverage ≥ 80% (цель 90%+)
- Автоматизированный CI/CD с security checks

**Текущий статус (06.04.2026):**
- 560 passed
- Coverage: **93%** (92.64% в последнем запуске)
- Все Pydantic V1 deprecation warnings устранены
- Тесты охватывают unit + integration + E2E

---

## 2. Стратегия тестирования

| Уровень       | Цель                                   | Инструменты                          | Coverage цель |
|---------------|----------------------------------------|--------------------------------------|---------------|
| Unit          | Отдельные функции и модули             | pytest, pytest-mock, respx           | 95%+          |
| Integration   | Взаимодействие компонентов             | pytest-asyncio, respx, clamd         | 85%+          |
| E2E           | Полный пользовательский сценарий       | httpx + TestClient                   | 70%+          |
| Security      | Шифрование, 2FA, ClamAV, audit        | Bandit, custom security tests        | 100%          |

---

## 3. Как тестировать ключевые компоненты

### 3.1 Шифрование (age)
**Файлы:** `app/crypto/crypto.py` + `tests/test_crypto/`

```bash
poetry run pytest tests/test_crypto/ -v

Что проверяется:

round-trip encrypt_file ↔ decrypt_file
Сравнение хэшей до/после
Ротация ключей (rotate_keys)
Обработка ошибок (неверный ключ, повреждённый файл)

### 3.2 Интеграционные тесты ClamAV
Файл: tests/test_api/test_upload.py
Используется мок ClamdNetworkSocket.
Проверяется:

Вирус обнаружен → 400 + audit log
ClamAV недоступен в prod-режиме → 503
Чистый файл проходит дальше

### 3.3 Тестирование 2FA
Файл: tests/test_api/test_auth.py

pyotp.TOTP с valid_window=1
Мокирование TOTP.verify
Полный цикл: setup → verify → login → disable


## 4. Реальные E2E сценарии
E2E-тесты проверяют полный пользовательский путь:

Полный цикл загрузки и скачивания
Регистрация/логин
Загрузка файла (/api/upload)
Проверка списка (/api/list)
Скачивание по токену (/api/download?token=...)
Автоматическое удаление после TTL

2FA + смена пароля
Логин с 2FA
Настройка 2FA
Смена пароля с подтверждением кода

Админские операции
Создание пользователя
Bulk-действия (deactivate, delete)
Удаление своего аккаунта (запрещено)


Запуск E2E:
poetry run pytest tests/e2e/ -v --tb=short

## 5.  Анализ покрытия (актуальный от 06.04.2026)
============================================================== tests coverage ===============================================================
Name                              Stmts   Miss  Cover   Missing
----------------------------------------------------------------
app/api/__init__.py                   9      0  100%
app/api/admin_users.py              210      0  100%
app/api/auth.py                     159      2   99%   34, 58
app/api/cleanup.py                   82      4   95%   137, 157-159
app/api/delete.py                    59      0  100%
app/api/delete_user.py               89      4   96%   79-80, 174-175
app/api/download.py                  91      0  100%
app/api/list.py                      64     22   66%   70-76, 80-139
app/api/stats.py                     93      0  100%
app/api/upload.py                   153      2   99%   338-339
app/cli.py                           58      6   90%   28, 93-99, 110
app/core/__init__.py                 54      6   89%   20-21, 25-27, 67
app/core/audit.py                    83     24   71%   48-49, 55-78, 109-110, 129-130, 152, 160-161
app/core/auth.py                     27      7   74%   31, 47-52, 58-63
app/core/auth_utils.py               14      0  100%
app/core/cleanup.py                  82     10   88%   50-51, 59, 67-69, 113, 128-130
app/core/config.py                   19      0  100%
app/core/constants.py                 6      0  100%
app/core/database.py                 12      0  100%
app/core/middleware.py               19      0  100%
app/core/rate_limiter.py             41      0  100%
app/core/security.py                  6      0  100%
app/core/storage.py                 128     18   86%   54-55, 74, 88-89, 99, 118-119, 124-132, 166
app/core/utils.py                    54     14   74%   80-85, 89-98
app/crypto/crypto.py                172      0  100%
app/main.py                         197     29   85%   53-54, 64-65, 152-154, 204-214, 218-223, 241-247, 361-362, 373-374
app/models/file.py                   26      1   96%   31
app/models/file_link.py              17      0  100%
app/models/user.py                   15      1   93%   31
----------------------------------------------------------------
TOTAL                              2039    150   93%

Критические модули (цель ≥ 95%):

crypto/crypto.py — 100%
api/upload.py — 99%
api/admin_users.py — 100%
api/download.py — 100%

### Модули ниже порога (требуют внимания)

| Модуль             | Текущий coverage | Целевой | Приоритет |
|--------------------|------------------|---------|-----------|
| `app/api/list.py`  | 66%              | 80%+    | Высокий   |
| `app/core/audit.py`| 71%              | 80%+    | Высокий   |
| `app/core/auth.py` | 74%              | 80%+    | Средний   |



## 6. Как запускать тесты
# Все тесты
poetry run pytest

# Конкретный модуль
poetry run pytest tests/test_api/test_upload.py -v

# С coverage
poetry run pytest --cov=app --cov-report=html

# Только integration / E2E
poetry run pytest -m integration
poetry run pytest -m e2e
Маркеры:

@pytest.mark.unit
@pytest.mark.integration
@pytest.mark.e2e


## 7. CI/CD
Файл: .github/workflows/ci.yml
Пайплайн запускает:

poetry install
pytest --cov=app --cov-report=xml
bandit -r app/
coverage fail-under=80
Docker build + push (при merge в main)

