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

// Загрузка списка файлов
async function loadFileList() {
    const fileList = document.getElementById('fileList');
    if (!fileList) return;
    
    fileList.innerHTML = '<div class="loading">⏳ Загрузка списка файлов...</div>';
    
    try {
        const response = await fetch(`${API_BASE}/list?x-api-key=${API_KEY}`);
        
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
            const downloadUrl = `${API_BASE}/download?filename=${encodeURIComponent(file.name)}&x-api-key=${API_KEY}`;
            html += `
                <div class="file-item">
                    <div class="file-info">
                        <div class="file-name">📄 ${file.original_name}</div>
                        <div class="file-size">
                            📏 ${file.size} байт<br>
                            🔐 ${file.name}
                        </div>
                    </div>
                    <a href="${downloadUrl}" class="btn-primary" download="${file.original_name}">
                        📥 Скачать
                    </a>
                </div>
            `;
        });
        
        fileList.innerHTML = html;
        
    } catch (error) {
        console.error('Ошибка загрузки списка файлов:', error);
        fileList.innerHTML = `<div class="error">❌ Ошибка: ${error.message}</div>`;
    }
}

// Обработка загрузки файла
async function handleUpload(event) {
    event.preventDefault();
    
    const form = event.target;
    const fileInput = form.querySelector('input[type="file"]');
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
            body: formData
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

// Обработка скачивания файла
async function handleDownload(event) {
    event.preventDefault();
    
    const form = event.target;
    const filenameInput = form.querySelector('input[name="filename"]');
    const filename = filenameInput.value.trim();
    
    if (!filename) {
        alert('Пожалуйста, введите имя файла');
        return;
    }
    
    // Просто открываем ссылку для скачивания
    const downloadUrl = `${API_BASE}/download?filename=${encodeURIComponent(filename)}&x-api-key=${API_KEY}`;
    window.open(downloadUrl, '_blank');
    
    // Очищаем поле
    filenameInput.value = '';
}



// Обновление списка файлов каждые 30 секунд
setInterval(loadFileList, 30000);