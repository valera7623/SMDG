# test_stats.py
import requests
import json
import time

print("=== ТЕСТ STATS ENDPOINT ===")

url = "http://localhost:8000"
api_key = "test-token-123"

def print_section(title):
    print(f"\n{'='*60}")
    print(f"{title}")
    print('='*60)

def print_json(data, indent=2):
    print(json.dumps(data, indent=indent, ensure_ascii=False))

# 1. Полная статистика
print_section("1. 📊 ПОЛНАЯ СТАТИСТИКА СИСТЕМЫ")
response = requests.get(f"{url}/api/stats", params={"x-api-key": api_key})

if response.status_code == 200:
    stats = response.json()
    print(f"✅ Статус: {response.status_code}")
    print(f"📅 Время сбора: {stats['timestamp']}")
    
    # Краткая сводка
    summary = stats['summary']
    print(f"\n📋 СВОДКА:")
    print(f"   Всего файлов: {summary['total_files']}")
    print(f"   Общий размер: {summary['total_size_mb']:.2f} MB")
    print(f"   Uptime: {summary['uptime']:.0f} секунд")
    print(f"   Статус: {summary['health']}")
    
    # Хранилище
    print(f"\n📁 ХРАНИЛИЩЕ:")
    for name, info in stats['storage']['directories'].items():
        if info['exists']:
            size_mb = info['size_bytes'] / (1024 * 1024)
            print(f"   {name}/: {info['file_count']} файлов, {size_mb:.2f} MB")
    
    # Файлы
    print(f"\n📄 ФАЙЛЫ:")
    files = stats['files']['encrypted']
    print(f"   Зашифрованных файлов: {files['count']}")
    
    if files['extensions']:
        print(f"   По расширениям:")
        for ext, data in files['extensions'].items():
            print(f"     {ext}: {data['count']} файлов ({data['total_size']/1024:.1f} KB)")
    
    # Система
    if 'system' in stats and 'cpu' in stats['system']:
        print(f"\n💻 СИСТЕМА:")
        print(f"   CPU: {stats['system']['cpu']['percent']}%")
        print(f"   Память: {stats['system']['memory']['percent']}%")
        print(f"   Диск: {stats['system']['disk']['percent']}%")
    
else:
    print(f"❌ Ошибка: {response.status_code}")
    print(f"Ответ: {response.text}")

# 2. Краткая сводка
print_section("2. 📋 КРАТКАЯ СВОДКА")
response = requests.get(f"{url}/api/stats/summary", params={"x-api-key": api_key})

if response.status_code == 200:
    summary = response.json()
    print(f"✅ Статус: {response.status_code}")
    print_json(summary)
else:
    print(f"❌ Ошибка: {response.status_code}")

# 3. Детальная проверка здоровья
print_section("3. 🩺 ДЕТАЛЬНАЯ ПРОВЕРКА ЗДОРОВЬЯ")
response = requests.get(f"{url}/api/stats/health", params={"x-api-key": api_key})

if response.status_code == 200:
    health = response.json()
    print(f"✅ Статус: {response.status_code}")
    print(f"Общий статус: {health['overall_status']}")
    
    print(f"\nПРОВЕРКИ:")
    for check in health['checks']:
        status_icon = "✅" if check['status'] == 'healthy' else "❌"
        print(f"   {status_icon} {check['check']}: {check['status']}")
        
        if 'details' in check:
            for key, value in check['details'].items():
                print(f"      {key}: {value}")
    
    print(f"\nРЕКОМЕНДАЦИИ:")
    for rec in health['recommendations']:
        print(f"   • {rec}")
else:
    print(f"❌ Ошибка: {response.status_code}")

# 4. Тест с неверным API ключом
print_section("4. 🔐 ТЕСТ БЕЗОПАСНОСТИ")
response = requests.get(f"{url}/api/stats", params={"x-api-key": "wrong-key"})
print(f"С неверным ключом: {response.status_code} - {response.json().get('detail', '')}")

print("\n" + "="*60)
print("✅ ТЕСТ ЗАВЕРШЕН")
print("="*60)

# 5. Пример использования в мониторинге
print_section("5. 📈 ПРИМЕР ДЛЯ МОНИТОРИНГА")
print("""
Пример команд для мониторинга:

# Получить общую статистику
curl "http://localhost:8000/api/stats/summary?x-api-key=test-token-123"

# Проверить здоровье системы
curl "http://localhost:8000/api/stats/health?x-api-key=test-token-123"

# Мониторинг дискового пространства (в bash)
curl -s "http://localhost:8000/api/stats?x-api-key=test-token-123" | \\
  python3 -c "import json,sys;d=json.load(sys.stdin);\\
  print(f'Disk used: {d[\"system\"][\"disk\"][\"percent\"]}%')"

# Мониторинг файлов (в bash)
curl -s "http://localhost:8000/api/stats/summary?x-api-key=test-token-123" | \\
  python3 -c "import json,sys;d=json.load(sys.stdin);\\
  print(f'Files: {d[\"total_files\"]}, Size: {d[\"total_size_mb\"]}MB')"
""")