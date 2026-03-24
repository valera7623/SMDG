// static/js/modules/admin-files.js

import { adminFiles as adminFilesAPI, system } from '../core/api.js';
import { showNotification }  from '../utils/notifications.js';
import { formatBytes }       from '../utils/formats.js';
import { escapeHtml, createElement } from '../utils/dom.js';

const REDIRECT_HOME = () => { window.location.href = '/'; };

// ── Список файлов (админ) ─────────────────────────────────────────────────────

export async function loadFiles() {
    const fileList = document.getElementById('fileList');
    if (!fileList) return;

    fileList.innerHTML = '<div class="loading">⏳ Загрузка...</div>';

    try {
        const data = await adminFilesAPI.list();

        if (data.count === 0) {
            fileList.innerHTML = '<div class="empty">📭 Нет загруженных файлов</div>';
            return;
        }

        fileList.innerHTML = '';
        data.files.forEach(file => fileList.appendChild(_createAdminFileItem(file)));

    } catch (error) {
        if (error.status === 401 || error.status === 403) { REDIRECT_HOME(); return; }
        fileList.innerHTML = `<div class="error">❌ ${escapeHtml(error.message)}</div>`;
    }
}

function _createAdminFileItem(file) {
    const item = document.createElement('div');
    item.className = 'file-item';

    const infoDiv = createElement('div', { className: 'file-info' });

    infoDiv.appendChild(createElement('div', { className: 'file-name',
        textContent: `📄 ${file.original_name || 'Без имени'}` }));
    infoDiv.appendChild(createElement('div', { className: 'file-size',
        textContent: `📏 ${formatBytes(file.size)}` }));
    infoDiv.appendChild(createElement('div', { className: 'file-id',
        textContent: `🔐 ${file.name || file.encrypted_name || '—'}` }));

    const actionsDiv = createElement('div', { className: 'file-actions' });

    const btnDl = createElement('button', { className: 'btn-secondary', textContent: '📥' });
    btnDl.addEventListener('click', () => downloadAdminFile(file.name));
    actionsDiv.appendChild(btnDl);

    const btnDel = createElement('button', { className: 'btn-danger', textContent: '🗑️' });
    btnDel.addEventListener('click', () => deleteAdminFile(file.name));
    actionsDiv.appendChild(btnDel);

    item.appendChild(infoDiv);
    item.appendChild(actionsDiv);
    return item;
}

// ── Скачивание ────────────────────────────────────────────────────────────────

async function downloadAdminFile(filename) {
    try {
        const response = await adminFilesAPI.download(filename);
        const blob      = await response.blob();

        let name = filename.replace(/\.age$/i, '');
        const disp = response.headers.get('Content-Disposition');
        if (disp) {
            const m = disp.match(/filename\*?=(?:UTF-8'')?([^;]+)/i);
            if (m) name = decodeURIComponent(m[1].trim().replace(/^"|"$/g, ''));
        }

        const url = URL.createObjectURL(blob);
        const a   = document.createElement('a');
        a.href = url; a.download = name; a.style.display = 'none';
        document.body.appendChild(a);
        a.click();
        URL.revokeObjectURL(url);
        document.body.removeChild(a);

    } catch (error) {
        if (error.status === 401 || error.status === 403) { REDIRECT_HOME(); return; }
        showNotification(`Ошибка скачивания: ${error.message}`, 'error');
    }
}

// ── Удаление ──────────────────────────────────────────────────────────────────

async function deleteAdminFile(filename) {
    if (!confirm(`Удалить файл «${filename}»?`)) return;

    try {
        const result = await adminFilesAPI.delete(filename);
        showNotification(`Файл удалён: ${result.message || 'OK'}`, 'success');
        await loadFiles();
    } catch (error) {
        if (error.status === 401 || error.status === 403) { REDIRECT_HOME(); return; }
        showNotification(`Ошибка: ${error.message}`, 'error');
    }
}

// ── Статистика системы ────────────────────────────────────────────────────────

export async function loadSystemStats() {
    await showSystemStats();

    const statsInfo = document.getElementById('statsInfo');
    if (!statsInfo) return;

    const wrap = document.createElement('div');
    wrap.style.marginTop = '20px';

    const btnDetailed = createElement('button', { className: 'btn-info',
        textContent: '📈 Детальная статистика' });
    btnDetailed.addEventListener('click', showDetailedStats);
    wrap.appendChild(btnDetailed);

    const btnRefresh = createElement('button', { className: 'btn-secondary',
        textContent: '🔄 Обновить', style: { marginLeft: '10px' } });
    btnRefresh.addEventListener('click', showSystemStats);
    wrap.appendChild(btnRefresh);

    statsInfo.appendChild(wrap);
}

export async function showSystemStats() {
    const statsInfo = document.getElementById('statsInfo');
    if (!statsInfo) return;

    statsInfo.innerHTML = '<div class="loading">⏳ Загрузка статистики...</div>';

    try {
        const data = await system.health();

        statsInfo.innerHTML = '';

        statsInfo.appendChild(createElement('h3', { textContent: '🩺 Статус системы' }));
        statsInfo.appendChild(createElement('p',  { textContent: `Статус: ${data.status || '—'}` }));
        statsInfo.appendChild(createElement('p',  { textContent: `Версия: ${data.version || '—'}` }));

        statsInfo.appendChild(createElement('h4', { textContent: 'Функции:' }));
        const ulFeatures = document.createElement('ul');
        if (data.features) {
            Object.entries(data.features).forEach(([k, v]) => {
                ulFeatures.appendChild(createElement('li', { textContent: `${k}: ${v ? '✅' : '❌'}` }));
            });
        }
        statsInfo.appendChild(ulFeatures);

        statsInfo.appendChild(createElement('h4', { textContent: 'Директории:' }));
        const ulDirs = document.createElement('ul');
        if (data.directories) {
            Object.entries(data.directories).forEach(([k, v]) => {
                ulDirs.appendChild(createElement('li', { textContent: `${k}: ${v ? '✅' : '❌'}` }));
            });
        }
        statsInfo.appendChild(ulDirs);

    } catch (error) {
        if (error.status === 401 || error.status === 403) { REDIRECT_HOME(); return; }
        statsInfo.innerHTML = `<div class="error">❌ ${escapeHtml(error.message)}</div>`;
    }
}

export async function showDetailedStats() {
    const statsInfo = document.getElementById('statsInfo');
    if (!statsInfo) return;

    try {
        const data = await system.stats();
        const pre  = createElement('pre', { textContent: JSON.stringify(data, null, 2) });
        statsInfo.appendChild(pre);
    } catch (error) {
        if (error.status === 401 || error.status === 403) { REDIRECT_HOME(); return; }
        showNotification(`Ошибка: ${error.message}`, 'error');
    }
}

// ── Статистика очистки ────────────────────────────────────────────────────────

export async function getCleanupStats() {
    const cleanupStats = document.getElementById('cleanupStats');
    if (!cleanupStats) return;

    try {
        const data = await adminFilesAPI.cleanupStats();
        cleanupStats.innerHTML = '';
        cleanupStats.appendChild(createElement('pre', { textContent: JSON.stringify(data, null, 2) }));
    } catch (error) {
        if (error.status === 401 || error.status === 403) { REDIRECT_HOME(); return; }
        cleanupStats.innerHTML = `<div class="error">❌ ${escapeHtml(error.message)}</div>`;
    }
}

// ── Принудительная очистка ────────────────────────────────────────────────────

export async function purgeAllFiles() {
    if (!confirm('⚠️ Удалить ВСЕ зашифрованные файлы?\nНЕОБРАТИМО!\n\nПродолжить?')) return;
    if (prompt('Введи "DELETE ALL" для подтверждения:') !== 'DELETE ALL') {
        showNotification('Отменено', 'info');
        return;
    }

    try {
        const result = await adminFilesAPI.purge();
        showNotification(
            `✅ Удалено: временных=${result.deleted.decrypted}, зашифрованных=${result.deleted.encrypted}`,
            'success'
        );
        if (result.errors?.length > 0) {
            showNotification(`Ошибки: ${result.errors.join('; ')}`, 'warning');
        }
        await loadFiles();
    } catch (error) {
        if (error.status === 401 || error.status === 403) { REDIRECT_HOME(); return; }
        showNotification(`Ошибка: ${error.message}`, 'error');
    }
}
