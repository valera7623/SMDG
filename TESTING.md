# TESTING.md

**Дата:** 06 апреля 2026  
**Версия SMDG:** 0.1  
**Цель документа:** Описать стратегию тестирования Secure Medical Data Gateway (SMDG) с акцентом на безопасность, шифрование и соответствие медицинским требованиям.

## 1. Введение

SMDG — это критически важная система для передачи медицинских данных.  
**Требования к QA:**  
- Полное покрытие шифрования (age)  
- Интеграционные тесты антивируса (ClamAV)  
- Тестирование 2FA/TOTP  
- Высокий coverage (минимум 80%, цель 90%+)  
- Автоматизированный CI/CD с security checks

**Текущий статус:**  
- 560 passed / 92.64% coverage  
- Все Pydantic V1 warnings устранены  
- Тесты охватывают unit + integration

## 2. Стратегия тестирования

| Уровень          | Цель                              | Инструменты                     | Coverage цель |
|------------------|-----------------------------------|---------------------------------|---------------|
| Unit             | Отдельные функции и модули        | pytest, pytest-mock, respx      | 95%+          |
| Integration      | Взаимодействие компонентов        | pytest-asyncio, respx, clamd    | 85%+          |
| E2E              | Полный сценарий upload/download   | httpx + TestClient              | 70%+          |
| Security         | Шифрование, 2FA, ClamAV           | Bandit, custom tests            | 100%          |

## 3. Как тестировать ключевые компоненты

### 3.1 Шифрование (age)

**Файл:** `app/crypto/crypto.py` + `tests/test_crypto/`

```bash
# Запуск тестов шифрования
poetry run pytest tests/test_crypto/ -v

Что проверяется:

encrypt_file / decrypt_file — round-trip целостность
Сравнение хэшей до/после
Key rotation (тест rotate_keys)
Обработка ошибок (неверный ключ, повреждённый файл)

Пример теста:

def test_encrypt_decrypt_roundtrip():
    original = b"medical data"
    encrypted = crypto_manager.encrypt_file(...)
    decrypted = crypto_manager.decrypt_file(...)
    assert decrypted == original

3.2 Интеграционные тесты ClamAV
Файл: tests/test_api/test_upload.py
Мокирование: 
@patch("clamd.ClamdNetworkSocket")
def test_clamav_virus_detected(mock_clamd):
    mock_clamd.return_value.instream.return_value = {"stream": ("FOUND", "Eicar-Test-Signature")}
    ...

Реальные тесты:

ClamAV недоступен в продакшен-режиме → 503
Вирус обнаружен → 400 + audit log
Чистый файл → проходит дальше

3.3 Тестирование 2FA
Файл: tests/test_api/test_auth.py
Как тестируется:

pyotp.TOTP с valid_window=1
Мокирование pyotp.TOTP.verify
Тесты: setup-2fa, verify-2fa-setup, login с/без кода, disable-2fa

Пример:

@patch("pyotp.TOTP.verify", return_value=True)
def test_login_with_2fa_success(mock_verify):
    ...

3.4 CI/CD (GitHub Actions)
Файл: .github/workflows/ci.yml
Что делает пайплайн:

poetry install
poetry run pytest --cov=app --cov-report=xml
bandit -r app/
coverage fail-under=80
Docker build + push (при merge в main)

Команды для локального запуска:
 
# Полный CI
poetry run pytest --cov=app --cov-report=html
poetry run bandit -r app/

4. Как запускать тесты
# Все тесты
poetry run pytest

# Только upload
poetry run pytest tests/test_api/test_upload.py -v

# С coverage
poetry run pytest --cov=app --cov-report=html

# Только integration
poetry run pytest -m integration

Маркеры:

@pytest.mark.unit
@pytest.mark.integration
@pytest.mark.e2e

5. Требования к coverage

Общий: ≥ 80% (сейчас 92.64%)
Критические модули (crypto, security, upload): ≥ 95%
При падении coverage — CI падает

6. Best practices для медицинского ПО

Все тесты шифрования — deterministic (round-trip)
ClamAV всегда мокится в unit-тестах
2FA тестируется только через pyotp
Audit logger всегда проверяется через assert_any_call
Нет реальных вызовов внешних сервисов в CI