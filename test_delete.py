# test_delete.py
import requests
import json

print("=== ТЕСТ УДАЛЕНИЯ ФАЙЛОВ ===")

url = "http://localhost:8000"
api_key = "test-token-123"

# 1. Сначала получим список файлов
print("\n1. Получение списка файлов...")
response = requests.get(f"{url}/api/list", params={"x-api-key": api_key})

if response.status_code == 200:
    files = response.json()
    print(f"   ✅ Найдено {files['count']} файлов")
    
    if files['count'] > 0:
        test_file = files['files'][0]['name']
        print(f"   📄 Тестовый файл для удаления: {test_file}")
        
        # 2. Тест удаления с подтверждением=false
        print("\n2. Тест удаления (только подтверждение)...")
        data = {
            "filename": test_file,
            "x-api-key": api_key,
            "confirm": "false",
            "reason": "Тестовое удаление"
        }
        
        response = requests.post(f"{url}/api/delete", data=data)
        print(f"   Статус: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            print(f"   ✅ Запрос на подтверждение успешен")
            print(f"   Ответ: {json.dumps(result, indent=2, ensure_ascii=False)}")
            
            # 3. Тест окончательного удаления
            if result.get('confirmation_required'):
                print("\n3. Окончательное удаление...")
                data['confirm'] = 'true'
                
                response = requests.post(f"{url}/api/delete", data=data)
                print(f"   Статус: {response.status_code}")
                
                if response.status_code == 200:
                    result = response.json()
                    print(f"   ✅ Файл успешно удален!")
                    print(f"   Ответ: {json.dumps(result, indent=2, ensure_ascii=False)}")
                else:
                    print(f"   ❌ Ошибка удаления: {response.text}")
        else:
            print(f"   ❌ Ошибка: {response.text}")
    else:
        print("   ℹ️  Нет файлов для тестирования удаления")
else:
    print(f"   ❌ Ошибка получения списка файлов: {response.status_code}")

print("\n=== ТЕСТ ЗАВЕРШЕН ===")