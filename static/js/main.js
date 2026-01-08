// static/js/main.js
const API_KEY = 'test-token-123';
const API_BASE = '/api';

// Инициализация при загрузке страницы
document.addEventListener('DOMContentLoaded', function() {
    // Загружаем список файлов
    loadFileList();
    
    // Настраиваем обработчики форм
    setupForms();
});

// Настройка обработчиков форм
function setupForms() {
    // Форма загрузки
    const uploadForm = document.getElementById('uploadForm');
    if (uploadForm) {
        uploadForm.addEventListener('submit', handleUpload);
    }
    
    // Форма скачивания
    const downloadForm = document.getElementById('downloadForm');
    if (downloadForm) {
        downloadForm.addEventListener('submit', handleDownload);
    }
}

// Заголовки для всех запросов (API-ключ в заголовке)
const headers = {
    'x-api-key': API_KEY
};

// Загрузка списка файлов
async function loadFileList() {
    const fileList = document.getElementById('fileList');
    if (!fileList) return;
    
    fileList.innerHTML = '<div class="loading">⏳ Загрузка списка файлов...</div>';
    
    try {
        const response = await fetch(`${API_BASE}/list`, {
            headers: headers
        });
        
        if (!response.ok) {
            throw new Error(`Ошибка: ${response.status}`);
        }
        
        const data = await response.json();
        
        if (data.count === 0) {
            fileList.innerHTML = '<div class="empty">📭 Нет загруженных файлов</div>';
            return;
        }
        
        let html = '';
        data.files.forEach(file => {
            html += `
                <div class="file-item">
                    <div class="file-info">
                        <div class="file-name">📄 ${file.original_name}</div>
                        <div class="file-size">
                            📏 ${file.size} байт<br>
                            🔐 ${file.name}
                        </div>
                    </div>
                    <a href="#" onclick="downloadFile('${file.name}')" class="btn-download">📥 Скачать</a>
                </div>
            `;
        });
        fileList.innerHTML = html;
        
    } catch (error) {
        console.error('Ошибка загрузки списка:', error);
        fileList.innerHTML = `<div class="error">❌ Ошибка: ${error.message}</div>`;
    }
}

// Обработка загрузки файла
async function handleUpload(event) {
    event.preventDefault();
    
    const form = event.target;
    const fileInput = form.querySelector('input[name="file"]');
    const submitBtn = form.querySelector('button[type="submit"]');
    
    if (!fileInput.files.length) {
        alert('Пожалуйста, выберите файл для загрузки');
        return;
    }
    
    const originalBtnText = submitBtn.textContent;
    submitBtn.textContent = '⏳ Шифрование...';
    submitBtn.disabled = true;
    
    try {
        const formData = new FormData(form);
        
        const response = await fetch(`${API_BASE}/upload`, {
            method: 'POST',
            body: formData,
            headers: headers  // ← API-ключ в заголовке
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || `Ошибка: ${response.status}`);
        }
        
        const result = await response.json();
        
        alert(`✅ Файл успешно загружен и зашифрован!\n\nЗашифрованный файл: ${result.encrypted_file}\nРазмер: ${result.original_size} → ${result.encrypted_size} байт`);
        
        // Очищаем поле файла
        fileInput.value = '';
        
        // Обновляем список файлов
        loadFileList();
        
    } catch (error) {
        console.error('Ошибка загрузки:', error);
        alert(`❌ Ошибка загрузки: ${error.message}`);
    } finally {
        submitBtn.textContent = originalBtnText;
        submitBtn.disabled = false;
    }
}

// Обработка формы скачивания (из формы)
async function handleDownload(event) {
    event.preventDefault();
    
    const form = event.target;
    const filenameInput = form.querySelector('input[name="filename"]');
    const filename = filenameInput.value.trim();
    
    if (!filename) {
        alert('Пожалуйста, введите имя файла');
        return;
    }
    
    await downloadFile(filename);
    
    // Очищаем поле
    filenameInput.value = '';
}

// Функция для скачивания файла (используется из списка и формы)
async function downloadFile(filename) {
    try {
        const response = await fetch(`${API_BASE}/download?filename=${encodeURIComponent(filename)}`, {
            headers: headers  // ← API-ключ в заголовке
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || `Ошибка: ${response.status}`);
        }
        
        // Создаём blob и скачиваем файл
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.style.display = 'none';
        a.href = url;
        
        // Извлекаем оригинальное имя из заголовка Content-Disposition
        const contentDisposition = response.headers.get('Content-Disposition');
        let originalName = filename.replace('.age', '');  // fallback
        if (contentDisposition) {
            const match = contentDisposition.match(/filename="?(.+)"?/i);
            if (match) originalName = match[1];
        }
        a.download = originalName;
        
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);
        
    } catch (error) {
        console.error('Ошибка скачивания:', error);
        alert(`❌ Ошибка скачивания: ${error.message}`);
    }
}

// Обновление списка файлов каждые 30 секунд
setInterval(loadFileList, 30000);