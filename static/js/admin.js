// static/js/admin.js

const API_BASE = '/api';

// ==================== ИНИЦИАЛИЗАЦИЯ ====================

document.addEventListener('DOMContentLoaded', function () {
    loadFiles();
    loadSystemStats();
});

// ==================== ЗАГРУЗКА СПИСКА ФАЙЛОВ ====================

async function loadFiles() {
    const fileList = document.getElementById('fileList');
    if (!fileList) return;

    fileList.innerHTML = '<div class="loading">⏳ Загрузка...</div>';

    try {
        const response = await fetch(`${API_BASE}/list`, {
            credentials: 'include'
        });

        if (!response.ok) {
            if (response.status === 401 || response.status === 403) {
                window.location.href = '/';
                return;
            }
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
        console.error('Ошибка загрузки списка файлов:', error);
        fileList.innerHTML = `<div class="error">❌ Ошибка: ${error.message}</div>`;
    }
}

// ==================== СКАЧИВАНИЕ ФАЙЛА ====================

async function downloadFile(filename) {
    try {
        const response = await fetch(`${API_BASE}/download?filename=${encodeURIComponent(filename)}`, {
            credentials: 'include'
        });

        if (!response.ok) {
            if (response.status === 401 || response.status === 403) {
                window.location.href = '/';
                return;
            }
            const error = await response.json();
            throw new Error(error.detail || `Ошибка: ${response.status}`);
        }

        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.style.display = 'none';
        a.href = url;

        // Пытаемся взять оригинальное имя из Content-Disposition
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

// ==================== УДАЛЕНИЕ ФАЙЛА ====================

async function deleteFile(filename) {
    if (!confirm(`Вы уверены, что хотите удалить файл "${filename}"?`)) {
        return;
    }

    try {
        const response = await fetch(`${API_BASE}/delete`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded'
            },
            body: new URLSearchParams({
                filename: filename,
                confirm: 'true',
                reason: 'manual_delete'
            }),
            credentials: 'include'
        });

        if (!response.ok) {
            if (response.status === 401 || response.status === 403) {
                window.location.href = '/';
                return;
            }
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

// ==================== СТАТИСТИКА СИСТЕМЫ ====================

async function loadSystemStats() {
    await showSystemStats();

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

async function showSystemStats() {
    const statsInfo = document.getElementById('statsInfo');
    if (!statsInfo) return;

    statsInfo.innerHTML = '<div class="loading">⏳ Загрузка статистики...</div>';

    try {
        const response = await fetch(`${API_BASE}/health`, {
            credentials: 'include'
        });

        if (!response.ok) {
            if (response.status === 401 || response.status === 403) {
                window.location.href = '/';
                return;
            }
            throw new Error(`Ошибка: ${response.status}`);
        }

        const data = await response.json();

        let html = '<h3>🩺 Статус системы</h3>';
        html += `<p>Статус: ${data.status}</p>`;
        html += `<p>Версия: ${data.version}</p>`;

        html += '<h4>Функции:</h4><ul>';
        for (const [key, value] of Object.entries(data.features)) {
            html += `<li>${key}: ${value ? '✅' : '❌'}</li>`;
        }
        html += '</ul>';

        html += '<h4>Директории:</h4><ul>';
        for (const [key, value] of Object.entries(data.directories)) {
            html += `<li>${key}: ${value ? '✅' : '❌'}</li>`;
        }
        html += '</ul>';

        statsInfo.innerHTML = html;

    } catch (error) {
        console.error('Ошибка загрузки статуса:', error);
        statsInfo.innerHTML = `<div class="error">❌ Ошибка: ${error.message}</div>`;
    }
}

async function showDetailedStats() {
    const statsInfo = document.getElementById('statsInfo');
    if (!statsInfo) return;

    try {
        const response = await fetch(`${API_BASE}/stats`, {
            credentials: 'include'
        });

        if (!response.ok) {
            if (response.status === 401 || response.status === 403) {
                window.location.href = '/';
                return;
            }
            throw new Error(`Ошибка: ${response.status}`);
        }

        const data = await response.json();

        statsInfo.innerHTML += `<pre>${JSON.stringify(data, null, 2)}</pre>`;

    } catch (error) {
        console.error('Ошибка детальной статистики:', error);
        alert(`❌ Ошибка: ${error.message}`);
    }
}

// ==================== СТАТИСТИКА ОЧИСТКИ ====================

async function getCleanupStats() {
    const cleanupStats = document.getElementById('cleanupStats');
    if (!cleanupStats) return;

    try {
        const response = await fetch(`${API_BASE}/cleanup/stats`, {
            credentials: 'include'
        });

        if (!response.ok) {
            if (response.status === 401 || response.status === 403) {
                window.location.href = '/';
                return;
            }
            throw new Error(`Ошибка: ${response.status}`);
        }

        const data = await response.json();
        cleanupStats.innerHTML = `<pre>${JSON.stringify(data, null, 2)}</pre>`;

    } catch (error) {
        console.error('Ошибка статистики очистки:', error);
        cleanupStats.innerHTML = `<div class="error">❌ Ошибка: ${error.message}</div>`;
    }
}

// ==================== ПРИНУДИТЕЛЬНАЯ ОЧИСТКА ВСЕХ ФАЙЛОВ ====================

async function purgeAllFiles() {
    if (!confirm('⚠️ ВНИМАНИЕ!\n\nУдалить ВСЕ зашифрованные файлы?\nНЕОБРАТИМО!\n\nПродолжить?')) return;

    const confirmText = prompt('Введи "DELETE ALL" для подтверждения:');
    if (confirmText !== 'DELETE ALL') {
        alert('Отменено.');
        return;
    }

    try {
        const response = await fetch(`${API_BASE}/cleanup/force`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include'
        });

        if (!response.ok) {
            if (response.status === 401 || response.status === 403) {
                window.location.href = '/';
                return;
            }
            let errData;
            try {
                errData = await response.json();
            } catch {
                errData = { detail: await response.text() || 'Нет ответа' };
            }
            throw new Error(errData.detail || `HTTP ${response.status}`);
        }

        const result = await response.json();
        alert(`✅ Удалено:\n- временных: ${result.deleted.decrypted}\n- зашифрованных: ${result.deleted.encrypted}`);
        if (result.errors?.length > 0) {
            alert(`Ошибок: ${result.errors.join('\n')}`);
        }
        loadFiles();

    } catch (error) {
        console.error('Purge error:', error);
        alert(`❌ Ошибка: ${error.message}`);
    }
}