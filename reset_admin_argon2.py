#!/usr/bin/env python3
"""
Сброс пароля администратора с использованием argon2id
"""
import subprocess
import sys

def generate_argon2_hash(password):
    """Генерирует хэш argon2id для пароля"""
    try:
        from passlib.hash import argon2
        # Используем те же параметры что и в исходном хэше
        hash_result = argon2.using(
            memory_cost=102400,  # 100 MB
            time_cost=2,         # 2 итерации
            parallelism=8,       # 8 потоков
            salt_size=16
        ).hash(password)
        return hash_result
    except ImportError:
        print("❌ Модуль passlib не установлен")
        print("💡 Установите: pip install passlib")
        sys.exit(1)

def reset_password(password="admin123"):
    """Сбрасывает пароль администратора"""
    print(f"🔄 СБРОС ПАРОЛЯ АДМИНИСТРАТОРА НА '{password}'")
    print("="*60)
    
    # Генерируем новый хэш
    print("🔐 Генерируем хэш argon2id...")
    new_hash = generate_argon2_hash(password)
    print(f"✅ Новый хэш сгенерирован:")
    print(f"   {new_hash[:80]}...")
    
    # SQL для обновления
    sql = f"UPDATE users SET hashed_password = '{new_hash}' WHERE username = 'admin';"
    
    # Сохраняем SQL в файл
    with open("update_password.sql", "w") as f:
        f.write(sql)
    
    # Выполняем SQL
    cmd = "PGPASSWORD=password psql -U smdg_user -h localhost -p 5432 -d smdg -f update_password.sql"
    
    print("\n💾 Обновляем пароль в базе данных...")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    
    if result.returncode == 0:
        print("✅ Пароль администратора обновлен!")
        print(f"\n🔑 Новые учетные данные:")
        print(f"   Логин: admin")
        print(f"   Пароль: {password}")
        
        # Проверяем
        print("\n🔍 Проверяем обновление...")
        cmd_check = "PGPASSWORD=password psql -U smdg_user -h localhost -p 5432 -d smdg -c \"SELECT username, SUBSTRING(hashed_password FROM 1 FOR 80) as hash FROM users WHERE username = 'admin';\""
        result_check = subprocess.run(cmd_check, shell=True, capture_output=True, text=True)
        
        if result_check.returncode == 0:
            print("✅ Хэш в базе данных:")
            print(result_check.stdout)
    else:
        print("❌ Ошибка при обновлении пароля:")
        print(result.stderr)
    
    # Удаляем временный файл
    import os
    if os.path.exists("update_password.sql"):
        os.remove("update_password.sql")
    
    return password

def test_login(password):
    """Тестирует вход с новым паролем"""
    print("\n🔐 ТЕСТИРОВАНИЕ ВХОДА")
    print("="*60)
    
    import time
    import requests
    
    # Ждем
    print("⏳ Ждем 2 секунды...")
    time.sleep(2)
    
    url = "http://127.0.0.1:8000/api/auth/login"
    data = {'username': 'admin', 'password': password}
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    
    print(f"🔑 Тестируем вход с паролем: '{password}'")
    
    try:
        response = requests.post(url, data=data, headers=headers, timeout=5)
        
        if response.status_code == 200:
            result = response.json()
            print(f"✅ УСПЕШНЫЙ ВХОД!")
            print(f"   Токен: {result.get('access_token', '')[:30]}...")
            print(f"   Роль: {result.get('role')}")
            print(f"   Имя: {result.get('username')}")
            return True
        elif response.status_code == 401:
            print(f"❌ 401 - Неверный пароль")
            print(f"   Ответ: {response.text}")
        elif response.status_code == 429:
            print(f"🚫 429 - Rate limit")
            print(f"   Ждем 10 секунд...")
            time.sleep(10)
            
            # Пробуем еще раз
            response = requests.post(url, data=data, headers=headers, timeout=5)
            if response.status_code == 200:
                print(f"✅ УСПЕХ после ожидания!")
                return True
        else:
            print(f"⚠️  Статус {response.status_code}")
            print(f"   Ответ: {response.text}")
            
    except Exception as e:
        print(f"🔥 Ошибка запроса: {e}")
    
    return False

def main():
    """Основная функция"""
    print("🔧 ВОССТАНОВЛЕНИЕ ДОСТУПА (ARGON2ID)")
    print("="*60)
    
    try:
        # Спрашиваем новый пароль
        print("💡 Приложение использует argon2id для хэширования")
        print("💡 Текущий пароль неизвестен, нужно сбросить")
        
        print("\n" + "="*60)
        new_password = input("Введите новый пароль для администратора (по умолчанию 'admin123'): ").strip()
        
        if not new_password:
            new_password = "admin123"
            print(f"Используем пароль по умолчанию: {new_password}")
        
        # 1. Сбрасываем пароль
        password = reset_password(new_password)
        
        # 2. Тестируем вход
        print("\n" + "="*60)
        success = test_login(password)
        
        if success:
            print(f"\n🎉 ДОСТУП ВОССТАНОВЛЕН!")
            print(f"   Используйте: admin / {password}")
        else:
            print(f"\n⚠️  Что-то пошло не так")
            print("💡 Проверьте:")
            print("   1. Сервер запущен")
            print("   2. Rate limiter не блокирует")
            print("   3. Попробуйте через 60 секунд")
        
    except KeyboardInterrupt:
        print("\n\n⏹️  Прервано пользователем")
    except Exception as e:
        print(f"\n💥 Ошибка: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "="*60)
    print("💡 КОМАНДА ДЛЯ РУЧНОГО СБРОСА:")
    print("="*60)
    print("python3 -c \"")
    print("from passlib.hash import argon2")
    print("hash = argon2.using(memory_cost=102400, time_cost=2, parallelism=8, salt_size=16).hash('ваш_пароль')")
    print("print('UPDATE users SET hashed_password =', repr(hash), 'WHERE username = \\'admin\\';')")
    print("\"")

if __name__ == "__main__":
    main()