#!/bin/bash
# test_login_limits.sh

echo "=== Тест 1: Неудачные попытки для user1 ==="
for i in {1..6}; do
  echo "Попытка $i для user1:"
  curl -s -X POST http://localhost:8000/api/auth/login \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "username=user1&password=wrong" \
    -w " HTTP %{http_code}\n" -o /dev/null
  sleep 1
done

echo -e "\n=== Тест 2: Попытка для user2 с того же IP ==="
echo "Попытка 1 для user2:"
curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=user2&password=wrong" \
  -w " HTTP %{http_code}\n" -o /dev/null

echo -e "\n=== Тест 3: Успешный вход для user2 ==="
curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=user2&password=popov7623" \
  -w " HTTP %{http_code}\n" -o /dev/null