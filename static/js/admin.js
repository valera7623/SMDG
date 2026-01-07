// static/js/admin.js
const API_KEY = 'test-token-123';
const API_BASE = '/api';

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

// Загрузка статистики системы
async function loadSystemStats() {
    try {
        // Статистика файлов
        const response = await fetch(`${API_BASE}/list?x-api-key=${API_KEY}`);
        if (response.ok) {
            const data = await response.json();
            document.getElementById('fileCount').textContent = `${data.count} файлов`;
        }
        
        // Проверка здоровья
        const healthResponse = await fetch('/health');
        if (healthResponse.ok) {
            document.getElementById('healthStatus').textContent = '✅ Работает';
        }
        
    } catch (error) {
        console.error('Ошибка загрузки статистики:', error);
    }
}

// Скачивание файла
async function downloadFile(filename) {
    const downloadUrl = `${API_BASE}/download?filename=${encodeURIComponent(filename)}&x-api-key=${API_KEY}`;
    window.open(downloadUrl, '_blank');
}

// Удаление файла

async function deleteFile(filename) {
    console.log(`Удаление файла: ${filename}`);
    
    if (!confirm(`Удалить файл "${filename}"?\nЭто действие необратимо.`)) {
        console.log('Удаление отменено пользователем');
        return;
    }
    
    const reason = prompt('Причина удаления (для аудита):', 'Ручное удаление администратором');
    if (reason === null) {
        console.log('Удаление отменено - не указана причина');
        return;
    }
    
    try {
        // Сначала запрашиваем подтверждение (confirm=false)
        const formData = new FormData();
        formData.append('filename', filename);
        formData.append('x-api-key', API_KEY);
        formData.append('confirm', 'false');
        formData.append('reason', reason || '');
        
        console.log('Отправка запроса на подтверждение...');
        
        let response = await fetch(`${API_BASE}/delete`, {
            method: 'POST',
            body: formData
        });
        
        let result = await response.json();
        console.log('Ответ сервера:', result);
        
        if (result.confirmation_required) {
            // Показываем информацию о файле
            const fileInfo = result.file_info;
            const finalConfirm = confirm(
                `ПОДТВЕРЖДЕНИЕ УДАЛЕНИЯ\n\n` +
                `📄 Файл: ${fileInfo.name}\n` +
                `📏 Размер: ${fileInfo.size} байт\n` +
                `🔐 Хеш: ${fileInfo.hash}\n\n` +
                `Для удаления введите "DELETE" в следующем окне.`
            );
            
            if (!finalConfirm) {
                alert('❌ Удаление отменено');
                return;
            }
            
            const deleteText = prompt('Для окончательного подтверждения введите DELETE:');
            if (deleteText !== 'DELETE') {
                alert('❌ Удаление отменено. Неправильное подтверждение.');
                return;
            }
            
            // Второй запрос - окончательное удаление (confirm=true)
            console.log('Отправка окончательного запроса на удаление...');
            formData.set('confirm', 'true');
            
            response = await fetch(`${API_BASE}/delete`, {
                method: 'POST',
                body: formData
            });
            
            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Ошибка удаления');
            }
            
            result = await response.json();
            console.log('Файл удален:', result);
            
            alert(`✅ Файл успешно удален!\n\nИмя: ${result.filename}\nХеш: ${result.hash.slice(0, 20)}...`);
            
            // Обновляем список файлов
            loadFiles();
            
        } else if (response.ok) {
            // Если подтверждение не требуется
            alert(`✅ Файл успешно удален!\n\nИмя: ${result.filename}`);
            loadFiles();
        } else {
            throw new Error(result.detail || 'Неизвестная ошибка');
        }
        
    } catch (error) {
        console.error('Ошибка удаления:', error);
        alert(`❌ Ошибка удаления: ${error.message}`);
    }
}

// Добавьте в static/js/admin.js новые функции
async function showCleanupStats() {
    try {
        const response = await fetch(`${API_BASE}/cleanup/stats?x-api-key=${API_KEY}`);
        
        if (!response.ok) {
            throw new Error(`Ошибка: ${response.status}`);
        }
        
        const stats = await response.json();
        
        let html = `
            <div class="stats-info">
                <h3>📊 Статистика временных файлов</h3>
                <p><strong>Всего файлов:</strong> ${stats.total_files}</p>
                <p><strong>Директория:</strong> ${stats.storage_dir}</p>
                <p><strong>TTL:</strong> ${(stats.ttl_seconds / 3600).toFixed(1)} часов</p>
        `;
        
        if (stats.files.length > 0) {
            html += `<h4>Файлы под управлением:</h4><ul>`;
            stats.files.forEach(file => {
                const ageMin = Math.floor(file.age_seconds / 60);
                const timeLeftMin = Math.floor(file.time_left_seconds / 60);
                html += `
                    <li>
                        ${file.name} (${file.size} байт)<br>
                        <small>Возраст: ${ageMin} мин, Удаление через: ${timeLeftMin} мин</small>
                    </li>
                `;
            });
            html += `</ul>`;
        } else {
            html += `<p>Нет файлов под управлением</p>`;
        }
        
        html += `</div>`;
        
        document.getElementById('cleanupStats').innerHTML = html;
        
    } catch (error) {
        console.error('Ошибка получения статистики:', error);
        document.getElementById('cleanupStats').innerHTML = 
            `<div class="error">❌ Ошибка: ${error.message}</div>`;
    }
}

async function forceCleanup() {
    if (!confirm('Принудительно очистить все временные файлы?\nЭто удалит все файлы в decrypted/.')) {
        return;
    }
    
    try {
        const response = await fetch(`${API_BASE}/cleanup/force?x-api-key=${API_KEY}`, {
            method: 'POST'
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Ошибка очистки');
        }
        
        const result = await response.json();
        alert(`✅ Очистка завершена!\nУдалено файлов: ${result.deleted}`);
        
        // Обновляем статистику
        showCleanupStats();
        
    } catch (error) {
        console.error('Ошибка очистки:', error);
        alert(`❌ Ошибка очистки: ${error.message}`);
    }
}

// Обновите функцию getCleanupStats в admin.js
async function getCleanupStats() {
    await showCleanupStats();
    
    // Добавьте кнопку принудительной очистки
    const cleanupStats = document.getElementById('cleanupStats');
    if (cleanupStats) {
        cleanupStats.innerHTML += `
            <div style="margin-top: 20px;">
                <button onclick="forceCleanup()" class="btn-warning">
                    🧹 Принудительная очистка
                </button>
            </div>
        `;
    }
}

// Добавьте в static/js/admin.js
async function showSystemStats() {
    try {
        const response = await fetch(`${API_BASE}/stats/summary?x-api-key=${API_KEY}`);
        
        if (!response.ok) {
            throw new Error(`Ошибка: ${response.status}`);
        }
        
        const stats = await response.json();
        
        let html = `
            <div class="stats-container">
                <h3>📊 Статистика системы</h3>
                <div class="stats-grid">
                    <div class="stat-card">
                        <h4>📁 Файлы</h4>
                        <p class="stat-number">${stats.total_files}</p>
                        <p class="stat-label">всего</p>
                    </div>
                    <div class="stat-card">
                        <h4>💾 Размер</h4>
                        <p class="stat-number">${stats.total_size_mb.toFixed(1)}</p>
                        <p class="stat-label">MB</p>
                    </div>
                    <div class="stat-card">
                        <h4>⏰ Uptime</h4>
                        <p class="stat-number">${stats.uptime_hours.toFixed(1)}</p>
                        <p class="stat-label">часов</p>
                    </div>
                    <div class="stat-card">
                        <h4>🏥 Статус</h4>
                        <p class="stat-number ${stats.health === 'healthy' ? 'healthy' : 'unhealthy'}">
                            ${stats.health === 'healthy' ? '✅' : '❌'}
                        </p>
                        <p class="stat-label">${stats.health}</p>
                    </div>
                </div>
        `;
        
        // Директории
        html += `<h4>📂 Директории</h4><div class="directories-grid">`;
        for (const [name, info] of Object.entries(stats.directories)) {
            if (info.files > 0 || info.size_mb > 0) {
                html += `
                    <div class="directory-card">
                        <strong>${name}/</strong><br>
                        <span>${info.files} файлов</span><br>
                        <small>${info.size_mb.toFixed(2)} MB</small>
                    </div>
                `;
            }
        }
        html += `</div>`;
        
        // Типы файлов
        if (stats.file_types && Object.keys(stats.file_types).length > 0) {
            html += `<h4>📄 Типы файлов</h4><div class="file-types">`;
            for (const [ext, count] of Object.entries(stats.file_types)) {
                html += `<span class="file-type-badge">${ext}: ${count}</span>`;
            }
            html += `</div>`;
        }
        
        // Очистка
        html += `<h4>🧹 Очистка</h4>`;
        html += `<p>Файлов для удаления: ${stats.cleanup.files_to_delete}</p>`;
        html += `<p>Временных файлов: ${stats.cleanup.temporary_files}</p>`;
        
        html += `</div>`;
        
        document.getElementById('statsInfo').innerHTML = html;
        
    } catch (error) {
        console.error('Ошибка получения статистики:', error);
        document.getElementById('statsInfo').innerHTML = 
            `<div class="error">❌ Ошибка: ${error.message}</div>`;
    }
}

async function showDetailedStats() {
    try {
        const response = await fetch(`${API_BASE}/stats?x-api-key=${API_KEY}`);
        
        if (!response.ok) {
            throw new Error(`Ошибка: ${response.status}`);
        }
        
        const stats = await response.json();
        
        // Открываем в новом окне с красивым форматированием
        const statsWindow = window.open('', '_blank');
        statsWindow.document.write(`
            <html>
            <head>
                <title>SMDG - Детальная статистика</title>
                <style>
                    body { font-family: Arial, sans-serif; padding: 20px; }
                    pre { background: #f5f5f5; padding: 15px; border-radius: 5px; overflow: auto; }
                    .timestamp { color: #666; font-size: 0.9em; }
                </style>
            </head>
            <body>
                <h1>📊 Детальная статистика SMDG</h1>
                <p class="timestamp">Собрано: ${stats.timestamp}</p>
                <pre>${JSON.stringify(stats, null, 2)}</pre>
            </body>
            </html>
        `);
        
    } catch (error) {
        console.error('Ошибка:', error);
        alert(`❌ Ошибка получения детальной статистики: ${error.message}`);
    }
}

// Обновите функцию loadSystemStats в admin.js
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

// Проверка статистики очистки
async function getCleanupStats() {
    const cleanupStats = document.getElementById('cleanupStats');
    if (!cleanupStats) return;
    
    try {
        // TODO: Реализовать endpoint для статистики очистки
        cleanupStats.innerHTML = '<div class="info">📊 Статистика очистки будет здесь</div>';
        
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
        // TODO: Реализовать endpoint для полной очистки
        alert('Функция полной очистки в разработке.');
        
    } catch (error) {
        console.error('Ошибка:', error);
        alert(`❌ Ошибка: ${error.message}`);
    }
}