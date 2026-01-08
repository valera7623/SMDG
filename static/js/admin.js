// static/js/admin.js
const API_KEY = 'test-token-123';
const API_BASE = '/api';

// Заголовки для всех запросов (API-ключ в заголовке)
const headers = {
    'Authorization': `Bearer ${localStorage.getItem("token")}`
};

// Инициализация
document.addEventListener('DOMContentLoaded', function() {
    loadFiles();
    loadSystemStats();
});

// Загрузка списка файлов
async function loadFiles() {
    const fileList = document.getElementById('fileList');
    if (!fileList) return;
    
    fileList.innerHTML = '<div class="loading">⏳ Загрузка...</div>';
    
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
                        <div class="file-size">📏 ${file.size} байт</div>
                        <div class="file-id">🔐 ${file.name}</div>
                    </div>
                    <div class="file-actions">
                        <button onclick="downloadFile('${file.name}')" class="btn-secondary">📥</button>
                        <button onclick="deleteFile('${file.name}')" class="btn-danger">🗑️</button>
                    </div>
                </div>
            `;
        });
        
        fileList.innerHTML = html;
        
    } catch (error) {
        console.error('Ошибка:', error);
        fileList.innerHTML = `<div class="error">❌ Ошибка: ${error.message}</div>`;
    }
}

// Функция скачивания файла
async function downloadFile(filename) {
    try {
        const response = await fetch(`${API_BASE}/download?filename=${encodeURIComponent(filename)}`, {
            headers: headers
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || `Ошибка: ${response.status}`);
        }
        
        // Создаём blob и скачиваем
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.style.display = 'none';
        a.href = url;
        
        // Извлекаем оригинальное имя из Content-Disposition
        const contentDisposition = response.headers.get('Content-Disposition');
        let originalName = filename.replace('.age', '');
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
        alert(`❌ Ошибка: ${error.message}`);
    }
}

// Удаление файла
async function deleteFile(filename) {
    if (!confirm(`Вы уверены, что хотите удалить файл "${filename}"?`)) {
        return;
    }
    
    try {
        const response = await fetch(`${API_BASE}/delete`, {
            method: 'POST',
            headers: {
                ...headers,
                'Content-Type': 'application/x-www-form-urlencoded'
            },
            body: new URLSearchParams({
                filename: filename,
                confirm: 'true',
                reason: 'manual_delete'
            })
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || `Ошибка: ${response.status}`);
        }
        
        const result = await response.json();
        alert(`✅ Файл успешно удалён: ${result.message || 'OK'}`);
        loadFiles();
        
    } catch (error) {
        console.error('Ошибка удаления:', error);
        alert(`❌ Ошибка: ${error.message}`);
    }
}

// Загрузка статистики системы
async function loadSystemStats() {
    await showSystemStats();
    
    // Добавьте кнопку для детальной статистики
    const statsInfo = document.getElementById('statsInfo');
    if (statsInfo) {
        statsInfo.innerHTML += `
            <div style="margin-top: 20px;">
                <button onclick="showDetailedStats()" class="btn-info">
                    📈 Показать детальную статистику
                </button>
                <button onclick="showSystemStats()" class="btn-secondary">
                    🔄 Обновить
                </button>
            </div>
        `;
    }
}

// Показать базовую статистику системы
async function showSystemStats() {
    const statsInfo = document.getElementById('statsInfo');
    if (!statsInfo) return;
    
    statsInfo.innerHTML = '<div class="loading">⏳ Загрузка статистики...</div>';
    
    try {
        const response = await fetch(`${API_BASE}/health`, {
            headers: headers
        });
        
        if (!response.ok) {
            throw new Error(`Ошибка: ${response.status}`);
        }
        
        const data = await response.json();
        
        let html = '<h3>🩺 Статус системы</h3>';
        html += `<p>Статус: ${data.status}</p>`;
        html += `<p>Версия: ${data.version}</p>`;
        
        // Отображаем фичи
        html += '<h4>Функции:</h4><ul>';
        for (const [key, value] of Object.entries(data.features)) {
            html += `<li>${key}: ${value ? '✅' : '❌'}</li>`;
        }
        html += '</ul>';
        
        // Директории
        html += '<h4>Директории:</h4><ul>';
        for (const [key, value] of Object.entries(data.directories)) {
            html += `<li>${key}: ${value ? '✅' : '❌'}</li>`;
        }
        html += '</ul>';
        
        statsInfo.innerHTML = html;
        
    } catch (error) {
        console.error('Ошибка:', error);
        statsInfo.innerHTML = `<div class="error">❌ Ошибка: ${error.message}</div>`;
    }
}

// Показать детальную статистику
async function showDetailedStats() {
    const statsInfo = document.getElementById('statsInfo');
    if (!statsInfo) return;
    
    try {
        const response = await fetch(`${API_BASE}/stats`, {
            headers: headers
        });
        
        if (!response.ok) {
            throw new Error(`Ошибка: ${response.status}`);
        }
        
        const data = await response.json();
        
        // Здесь отобразите детальную статистику
        // Например, добавьте JSON-вьюер или парсите данные
        
        statsInfo.innerHTML += `<pre>${JSON.stringify(data, null, 2)}</pre>`;
        
    } catch (error) {
        console.error('Ошибка:', error);
        alert(`❌ Ошибка получения детальной статистики: ${error.message}`);
    }
}

// Проверка статистики очистки
async function getCleanupStats() {
    const cleanupStats = document.getElementById('cleanupStats');
    if (!cleanupStats) return;
    
    try {
        const response = await fetch(`${API_BASE}/cleanup/stats`, {
            headers: headers
        });
        
        if (!response.ok) {
            throw new Error(`Ошибка: ${response.status}`);
        }
        
        const data = await response.json();
        
        // Отобразите данные
        cleanupStats.innerHTML = `<pre>${JSON.stringify(data, null, 2)}</pre>`;
        
    } catch (error) {
        console.error('Ошибка:', error);
        cleanupStats.innerHTML = `<div class="error">❌ Ошибка: ${error.message}</div>`;
    }
}

// Очистка всех файлов
async function purgeAllFiles() {
    if (!confirm('⚠️ ВНИМАНИЕ!\n\nВы собираетесь удалить ВСЕ зашифрованные файлы.\nЭто действие НЕОБРАТИМО.\n\nПродолжить?')) {
        return;
    }
    
    const confirmText = prompt('Для подтверждения введите "DELETE ALL":');
    if (confirmText !== 'DELETE ALL') {
        alert('Отменено. Неправильное подтверждение.');
        return;
    }
    
    try {
        const response = await fetch(`${API_BASE}/cleanup/force`, {
            method: 'POST',
            headers: headers
        });
        
        if (!response.ok) {
            throw new Error(`Ошибка: ${response.status}`);
        }
        
        const result = await response.json();
        alert(`✅ Успешно удалено ${result.deleted} файлов`);
        loadFiles();  // Обновляем список
        
    } catch (error) {
        console.error('Ошибка:', error);
        alert(`❌ Ошибка: ${error.message}`);
    }
}