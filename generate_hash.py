from passlib.hash import argon2

password = "admin123"
hashed = argon2.hash(password)
print(f"Хеш для '{password}': {hashed}")

# Проверка
print(f"Проверка: {argon2.verify('admin123', hashed)}")