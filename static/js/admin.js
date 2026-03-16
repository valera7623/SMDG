// static/js/admin.js

const API_BASE = '/api';

// ==================== ИНИЦИАЛИЗАЦИЯ ====================

document.addEventListener('DOMContentLoaded', function () {
    loadFiles();
    loadSystemStats();
});

// ==================== Безопасный escape ====================
function escapeHtml(unsafe) {
    if (typeof unsafe !== 'string') return '';
    return unsafe
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;")
        .replace(/\//g, "&#x2F;");
}

// ==================== Форматирование размера файла ====================
function formatFileSize(bytes) {
    if (!bytes && bytes !== 0) return '—';
    const units = ['Б', 'КБ', 'МБ', 'ГБ', 'ТБ'];
    let size = bytes;
    let unitIndex = 0;
    while (size >= 1024 && unitIndex < units.length - 1) {
        size /= 1024;
        unitIndex++;
    }
    return `${size.toFixed(2)} ${units[unitIndex]}`;
}

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

        fileList.innerHTML = ''; // очищаем перед рендером

        data.files.forEach(file => {
            const item = document.createElement('div');
            item.className = 'file-item';

            // Информация о файле
            const infoDiv = document.createElement('div');
            infoDiv.className = 'file-info';

            // Имя файла
            const nameDiv = document.createElement('div');
            nameDiv.className = 'file-name';
            nameDiv.textContent = `📄 ${escapeHtml(file.original_name || 'Без имени')}`;
            infoDiv.appendChild(nameDiv);

            // Размер
            const sizeDiv = document.createElement('div');
            sizeDiv.className = 'file-size';
            sizeDiv.textContent = `📏 ${formatFileSize(file.size)}`;
            infoDiv.appendChild(sizeDiv);

            // ID / Encrypted name
            const idDiv = document.createElement('div');
            idDiv.className = 'file-id';
            idDiv.textContent = `🔐 ${escapeHtml(file.name || file.encrypted_name || '—')}`;
            infoDiv.appendChild(idDiv);

            item.appendChild(infoDiv);

            // Кнопки действий
            const actionsDiv = document.createElement('div');
            actionsDiv.className = 'file-actions';

            const btnDownload = document.createElement('button');
            btnDownload.className = 'btn-secondary';
            btnDownload.textContent = '📥';
            btnDownload.onclick = () => downloadFile(file.name);
            actionsDiv.appendChild(btnDownload);

            const btnDelete = document.createElement('button');
            btnDelete.className = 'btn-danger';
            btnDelete.textContent = '🗑️';
            btnDelete.onclick = () => deleteFile(file.name);
            actionsDiv.appendChild(btnDelete);

            item.appendChild(actionsDiv);

            fileList.appendChild(item);
        });

    } catch (error) {
        console.error('Ошибка загрузки списка файлов:', error);

        fileList.innerHTML = '';
        const errorDiv = document.createElement('div');
        errorDiv.className = 'error';
        errorDiv.textContent = `❌ Ошибка: ${escapeHtml(error.message || 'Неизвестная ошибка')}`;
        fileList.appendChild(errorDiv);
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
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.detail || `Ошибка: ${response.status}`);
        }

        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.style.display = 'none';
        a.href = url;

        // Пытаемся взять оригинальное имя из Content-Disposition
        let originalName = filename.replace(/\.age$/i, '');
        const disposition = response.headers.get('Content-Disposition');
        if (disposition) {
            const match = disposition.match(/filename\*?=(?:UTF-8'')?([^;]+)/i);
            if (match) originalName = decodeURIComponent(match[1].trim().replace(/^"|"$/g, ''));
        }

        a.download = originalName;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);

    } catch (error) {
        console.error('Ошибка скачивания:', error);
        alert(`❌ Ошибка: ${escapeHtml(error.message || 'Не удалось скачать файл')}`);
    }
}

// ==================== УДАЛЕНИЕ ФАЙЛА ====================

async function deleteFile(filename) {
    if (!confirm(`Вы уверены, что хотите удалить файл "${escapeHtml(filename)}"?`)) {
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
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.detail || `Ошибка: ${response.status}`);
        }

        const result = await response.json();
        alert(`✅ Файл успешно удалён: ${escapeHtml(result.message || 'OK')}`);
        loadFiles();

    } catch (error) {
        console.error('Ошибка удаления:', error);
        alert(`❌ Ошибка: ${escapeHtml(error.message || 'Не удалось удалить файл')}`);
    }
}

// ==================== СТАТИСТИКА СИСТЕМЫ ====================

async function loadSystemStats() {
    await showSystemStats();

    const statsInfo = document.getElementById('statsInfo');
    if (!statsInfo) return;

    const actionsDiv = document.createElement('div');
    actionsDiv.style.marginTop = '20px';

    const btnDetailed = document.createElement('button');
    btnDetailed.className = 'btn-info';
    btnDetailed.textContent = '📈 Показать детальную статистику';
    btnDetailed.onclick = showDetailedStats;
    actionsDiv.appendChild(btnDetailed);

    const btnRefresh = document.createElement('button');
    btnRefresh.className = 'btn-secondary';
    btnRefresh.textContent = '🔄 Обновить';
    btnRefresh.onclick = showSystemStats;
    actionsDiv.appendChild(btnRefresh);

    statsInfo.appendChild(actionsDiv);
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

        statsInfo.innerHTML = ''; // очищаем

        const h3 = document.createElement('h3');
        h3.textContent = '🩺 Статус системы';
        statsInfo.appendChild(h3);

        const pStatus = document.createElement('p');
        pStatus.textContent = `Статус: ${data.status || '—'}`;
        statsInfo.appendChild(pStatus);

        const pVersion = document.createElement('p');
        pVersion.textContent = `Версия: ${data.version || '—'}`;
        statsInfo.appendChild(pVersion);

        const h4Features = document.createElement('h4');
        h4Features.textContent = 'Функции:';
        statsInfo.appendChild(h4Features);

        const ulFeatures = document.createElement('ul');
        if (data.features) {
            Object.entries(data.features).forEach(([key, value]) => {
                const li = document.createElement('li');
                li.textContent = `${key}: ${value ? '✅' : '❌'}`;
                ulFeatures.appendChild(li);
            });
        }
        statsInfo.appendChild(ulFeatures);

        const h4Dirs = document.createElement('h4');
        h4Dirs.textContent = 'Директории:';
        statsInfo.appendChild(h4Dirs);

        const ulDirs = document.createElement('ul');
        if (data.directories) {
            Object.entries(data.directories).forEach(([key, value]) => {
                const li = document.createElement('li');
                li.textContent = `${key}: ${value ? '✅' : '❌'}`;
                ulDirs.appendChild(li);
            });
        }
        statsInfo.appendChild(ulDirs);

    } catch (error) {
        console.error('Ошибка загрузки статуса:', error);
        statsInfo.innerHTML = '';
        const errorDiv = document.createElement('div');
        errorDiv.className = 'error';
        errorDiv.textContent = `❌ Ошибка: ${escapeHtml(error.message || 'Неизвестная ошибка')}`;
        statsInfo.appendChild(errorDiv);
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

        const pre = document.createElement('pre');
        pre.textContent = JSON.stringify(data, null, 2);
        statsInfo.appendChild(pre);

    } catch (error) {
        console.error('Ошибка детальной статистики:', error);
        alert(`❌ Ошибка: ${escapeHtml(error.message || 'Не удалось загрузить статистику')}`);
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

        cleanupStats.innerHTML = '';
        const pre = document.createElement('pre');
        pre.textContent = JSON.stringify(data, null, 2);
        cleanupStats.appendChild(pre);

    } catch (error) {
        console.error('Ошибка статистики очистки:', error);
        cleanupStats.innerHTML = '';
        const errorDiv = document.createElement('div');
        errorDiv.className = 'error';
        errorDiv.textContent = `❌ Ошибка: ${escapeHtml(error.message || 'Неизвестная ошибка')}`;
        cleanupStats.appendChild(errorDiv);
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