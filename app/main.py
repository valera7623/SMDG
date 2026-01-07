# app/main.py
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from app.api import upload, download, list
from app.core import init_keys
import asyncio

app = FastAPI(
    title="Secure Medical Data Gateway v0.1",
    version="0.1.0"
)

app.include_router(upload.router, prefix="/api")
app.include_router(download.router, prefix="/api")
app.include_router(list.router, prefix="/api")

# Глобальная переменная для хранения публичного ключа после инициализации
public_key_initialized = False

@app.on_event("startup")
async def startup_event():
    global public_key_initialized
    print("🚀 Запуск SMDG...")
    
    try:
        # Инициализируем ключи и получаем публичный ключ
        public_key = await init_keys()
        if public_key:
            public_key_initialized = True
            print(f"✅ Публичный ключ инициализирован: {public_key[:30]}...")
        else:
            print("❌ Не удалось инициализировать публичный ключ")
    except Exception as e:
        print(f"❌ Ошибка при инициализации ключей: {e}")
        # Можно продолжить работу без ключей? Нет, это критично
        raise
    
    print("✅ SMDG запущен")

# app/main.py - обновите функцию index()
@app.get("/", response_class=HTMLResponse)
async def index():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>SMDG v0.1 - Secure Medical Data Gateway</title>
        <meta charset="utf-8">
        <style>
            body {
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                max-width: 1000px;
                margin: 0 auto;
                padding: 20px;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
            }
            
            .container {
                background: white;
                padding: 40px;
                border-radius: 15px;
                box-shadow: 0 20px 60px rgba(0,0,0,0.3);
                margin-bottom: 30px;
            }
            
            h1 {
                color: #2c3e50;
                text-align: center;
                margin-bottom: 10px;
                font-size: 2.5em;
            }
            
            .subtitle {
                text-align: center;
                color: #7f8c8d;
                margin-bottom: 40px;
                font-size: 1.2em;
            }
            
            .status {
                padding: 15px;
                border-radius: 8px;
                margin-bottom: 25px;
                text-align: center;
                font-weight: bold;
                font-size: 1.1em;
            }
            
            .status.ok {
                background: #d4edda;
                color: #155724;
                border: 2px solid #c3e6cb;
            }
            
            .api-key-box {
                background: #fff3cd;
                border: 2px solid #ffeaa7;
                padding: 15px;
                border-radius: 8px;
                text-align: center;
                margin: 20px 0;
                font-family: 'Courier New', monospace;
                font-size: 1.2em;
                font-weight: bold;
            }
            
            .section {
                margin: 40px 0;
                padding: 25px;
                background: #f8f9fa;
                border-radius: 10px;
                border-left: 5px solid #3498db;
            }
            
            .section h2 {
                color: #2c3e50;
                margin-top: 0;
                display: flex;
                align-items: center;
                gap: 10px;
            }
            
            .section h2::before {
                font-size: 1.5em;
            }
            
            form {
                margin: 20px 0;
            }
            
            input[type="file"], input[type="text"] {
                width: 100%;
                padding: 12px;
                margin: 10px 0;
                border: 2px solid #ddd;
                border-radius: 6px;
                font-size: 16px;
                box-sizing: border-box;
            }
            
            input[type="submit"] {
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                padding: 15px 30px;
                border: none;
                border-radius: 6px;
                cursor: pointer;
                font-size: 16px;
                font-weight: bold;
                width: 100%;
                margin-top: 10px;
                transition: transform 0.2s;
            }
            
            input[type="submit"]:hover {
                transform: translateY(-2px);
                box-shadow: 0 5px 15px rgba(0,0,0,0.2);
            }
            
            .file-list {
                margin-top: 20px;
                max-height: 300px;
                overflow-y: auto;
            }
            
            .file-item {
                padding: 12px;
                background: white;
                border-radius: 6px;
                margin: 8px 0;
                display: flex;
                justify-content: space-between;
                align-items: center;
                border: 1px solid #e9ecef;
            }
            
            .file-info {
                flex-grow: 1;
            }
            
            .file-name {
                font-weight: bold;
                color: #2c3e50;
            }
            
            .file-size {
                color: #7f8c8d;
                font-size: 0.9em;
            }
            
            .btn {
                padding: 8px 16px;
                background: #28a745;
                color: white;
                border: none;
                border-radius: 4px;
                cursor: pointer;
                font-weight: bold;
                text-decoration: none;
                display: inline-block;
            }
            
            .btn:hover {
                background: #218838;
            }
            
            .info-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
                gap: 20px;
                margin-top: 30px;
            }
            
            .info-card {
                background: #f8f9fa;
                padding: 20px;
                border-radius: 8px;
                border-top: 4px solid #3498db;
            }
            
            .info-card h3 {
                margin-top: 0;
                color: #2c3e50;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🔐 Secure Medical Data Gateway</h1>
            <div class="subtitle">v0.1 - Безопасная передача медицинских файлов</div>
            
            <div class="status ok">
                ✅ Система работает. Ключи шифрования инициализированы.
            </div>
            
            <div class="api-key-box">
                🔑 API Key для тестирования: <code>test-token-123</code>
            </div>
            
            <!-- Секция загрузки файла -->
            <div class="section">
                <h2>📤 Загрузить медицинский файл</h2>
                <p>Файл будет автоматически зашифрован и сохранен в безопасном хранилище.</p>
                
                <form action="/api/upload" method="post" enctype="multipart/form-data">
                    <input type="hidden" name="x-api-key" value="test-token-123">
                    <input type="file" name="file" required accept=".pdf,.doc,.docx,.txt,.jpg,.png,.dcm">
                    <input type="submit" value="🔐 Зашифровать и загрузить">
                </form>
                
                # Обновите script часть в main.py
                <script>
    // Обработка формы загрузки
    document.querySelector('form[action="/api/upload"]').addEventListener('submit', async function(e) {
        e.preventDefault();
        
        const form = this;
        const formData = new FormData(form);
        const submitBtn = form.querySelector('input[type="submit"]');
        const originalBtnText = submitBtn.value;
        
        // Показываем индикатор загрузки
        submitBtn.value = "⏳ Шифрование...";
        submitBtn.disabled = true;
        
        try {
            const response = await fetch('/api/upload', {
                method: 'POST',
                body: formData
            });
            
            if (response.ok) {
                const result = await response.json();
                
                // Показываем успешное сообщение
                alert(`✅ Файл успешно загружен и зашифрован!\n\nЗашифрованный файл: ${result.encrypted_file}\nРазмер: ${result.original_size} → ${result.encrypted_size} байт`);
                
                // Очищаем поле файла
                form.querySelector('input[type="file"]').value = '';
                
                // Автоматически обновляем список файлов
                loadFileList();
            } else {
                const error = await response.json();
                alert(`❌ Ошибка загрузки: ${error.detail || response.statusText}`);
            }
        } catch (error) {
            console.error('Ошибка:', error);
            alert('❌ Ошибка при загрузке файла');
        } finally {
            // Восстанавливаем кнопку
            submitBtn.value = originalBtnText;
            submitBtn.disabled = false;
        }
    });
    
    // Функция загрузки списка файлов
    async function loadFileList() {
        const fileList = document.getElementById('fileList');
        fileList.innerHTML = '<p style="text-align: center; color: #7f8c8d;">⏳ Загрузка списка файлов...</p>';
        
        try {
            const params = new URLSearchParams({
                'x-api-key': 'test-token-123'
            });
            
            const response = await fetch('/api/list?' + params.toString());
            
            if (response.ok) {
                const data = await response.json();
                
                if (data.count === 0) {
                    fileList.innerHTML = '<p style="text-align: center; color: #7f8c8d;">📭 Нет загруженных файлов</p>';
                    return;
                }
                
                let html = '';
                data.files.forEach(file => {
                    const downloadUrl = `/api/download?filename=${encodeURIComponent(file.name)}&x-api-key=test-token-123`;
                    html += `
                        <div class="file-item">
                            <div class="file-info">
                                <div class="file-name">📄 ${file.original_name}</div>
                                <div class="file-size">
                                    📏 Оригинал: ${file.size} байт<br>
                                    🔐 Зашифрован: ${file.name}
                                </div>
                            </div>
                            <a href="${downloadUrl}" class="btn" download="${file.original_name}">
                                📥 Скачать
                            </a>
                        </div>
                    `;
                });
                
                fileList.innerHTML = html;
            } else {
                fileList.innerHTML = '<p style="text-align: center; color: #dc3545;">❌ Ошибка загрузки списка файлов</p>';
            }
        } catch (error) {
            console.error('Ошибка:', error);
            fileList.innerHTML = '<p style="text-align: center; color: #dc3545;">❌ Ошибка соединения</p>';
        }
    }
    
    // Загружаем список файлов при загрузке страницы
    document.addEventListener('DOMContentLoaded', loadFileList);
    
    // Автоматически обновляем список каждые 30 секунд
    setInterval(loadFileList, 30000);
</script>
            </div>
            
            <!-- Секция списка файлов -->
            <div class="section">
                <h2>📋 Список зашифрованных файлов</h2>
                <p>Все файлы хранятся в зашифрованном виде. Для скачивания требуется дешифрование.</p>
                
                <form action="/api/list" method="get">
                    <input type="hidden" name="x-api-key" value="test-token-123">
                    <input type="submit" value="🔄 Обновить список файлов">
                </form>
                
                <div class="file-list" id="fileList">
                    <!-- Список файлов появится здесь после нажатия кнопки -->
                </div>
                
                <script>
                    // Обработка формы списка файлов
                    document.querySelector('form[action="/api/list"]').addEventListener('submit', async function(e) {
                        e.preventDefault();
                        
                        const formData = new FormData(this);
                        const params = new URLSearchParams(formData);
                        
                        try {
                            const response = await fetch('/api/list?' + params.toString());
                            if (response.ok) {
                                const data = await response.json();
                                const fileList = document.getElementById('fileList');
                                
                                if (data.count === 0) {
                                    fileList.innerHTML = '<p style="text-align: center; color: #7f8c8d;">Нет загруженных файлов</p>';
                                    return;
                                }
                                
                                let html = '';
                                data.files.forEach(file => {
                                    html += `
                                        <div class="file-item">
                                            <div class="file-info">
                                                <div class="file-name">${file.original_name}</div>
                                                <div class="file-size">${file.size} байт (зашифрован: ${file.name})</div>
                                            </div>
                                            <form action="/api/download" method="post" style="margin: 0;">
                                                <input type="hidden" name="x-api-key" value="test-token-123">
                                                <input type="hidden" name="filename" value="${file.name}">
                                                <button type="submit" class="btn">📥 Скачать</button>
                                            </form>
                                        </div>
                                    `;
                                });
                                
                                fileList.innerHTML = html;
                            } else {
                                alert('Ошибка загрузки списка файлов: ' + response.status);
                            }
                        } catch (error) {
                            console.error('Ошибка:', error);
                            alert('Ошибка при загрузке списка файлов');
                        }
                    });
                </script>
            </div>
            
            <!-- Секция ручного скачивания -->
            <div class="section">
                <h2>📥 Ручное скачивание файла</h2>
                <p>Введите точное имя зашифрованного файла для скачивания и расшифровки.</p>
                
                <form action="/api/download" method="post">
                    <input type="hidden" name="x-api-key" value="test-token-123">
                    <input type="text" name="filename" placeholder="например: medical_report.pdf.age" required>
                    <input type="submit" value="🔓 Скачать и расшифровать">
                </form>
            </div>
            
            <!-- Информация о системе -->
            <div class="info-grid">
                <div class="info-card">
                    <h3>🏥 Назначение</h3>
                    <p>Безопасный обмен медицинскими данными между врачами и клиниками с использованием end-to-end шифрования.</p>
                </div>
                
                <div class="info-card">
                    <h3>🔐 Безопасность</h3>
                    <p>Все файлы шифруются на сервере с использованием алгоритма age. Ключи хранятся отдельно от данных.</p>
                </div>
                
                <div class="info-card">
                    <h3>📊 Статистика</h3>
                    <p>Система автоматически удаляет временные файлы. Зашифрованные данные хранятся до ручного удаления.</p>
                </div>
            </div>
            
            <div style="text-align: center; margin-top: 40px; color: #7f8c8d; font-size: 0.9em;">
                <p>SMDG v0.1 | Для демонстрационных целей | API Key: test-token-123</p>
                <p>Проверка системы: <a href="/health" target="_blank">/health</a> | Документация API: <a href="/docs" target="_blank">/docs</a></p>
            </div>
        </div>
    </body>
    </html>
    """


@app.get("/health")
async def health_check():
    return {
        "status": "healthy", 
        "service": "smdg",
        "keys_initialized": public_key_initialized
    }
