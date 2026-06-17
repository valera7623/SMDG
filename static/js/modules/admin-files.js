// static/js/modules/admin-files.js

import { adminFiles as adminFilesAPI, system } from '../core/api.js';
import { showNotification }  from '../utils/notifications.js';
import { formatBytes }       from '../utils/formats.js';
import { escapeHtml, createElement } from '../utils/dom.js';
import { t } from '../utils/i18n.js';

import { redirectToLogin } from '../spa-nav.js';

const REDIRECT_HOME = () => redirectToLogin();

// ── Admin file list ──────────────────────────────────────────────────────────

export async function loadFiles() {
    const fileList = document.getElementById('fileList');
    if (!fileList) return;

    fileList.innerHTML = `<div class="loading">⏳ ${t('common.loading', 'Loading…')}</div>`;

    try {
        const data = await adminFilesAPI.list();

        if (data.count === 0) {
            fileList.innerHTML = `<div class="empty">📭 ${t('admin_files.empty', 'No uploaded files')}</div>`;
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

    const displayName = file.original_name || t('admin_files.no_name', 'Untitled');
    infoDiv.appendChild(createElement('div', { className: 'file-name',
        textContent: `📄 ${displayName}` }));
    infoDiv.appendChild(createElement('div', { className: 'file-size',
        textContent: `📏 ${formatBytes(file.size)}` }));
    infoDiv.appendChild(createElement('div', { className: 'file-id',
        textContent: `🔐 ${file.name || file.encrypted_name || '—'}` }));

    const actionsDiv = createElement('div', { className: 'file-actions' });

    const btnDl = createElement('button', {
        className: 'btn-secondary',
        textContent: '📥',
        title: t('files.btn_download', 'Download'),
    });
    btnDl.addEventListener('click', () => downloadAdminFile(file.name));
    actionsDiv.appendChild(btnDl);

    const btnDel = createElement('button', {
        className: 'btn-danger',
        textContent: '🗑️',
        title: t('files.btn_delete', 'Delete'),
    });
    btnDel.addEventListener('click', () => deleteAdminFile(file.name));
    actionsDiv.appendChild(btnDel);

    item.appendChild(infoDiv);
    item.appendChild(actionsDiv);
    return item;
}

// ── Download ─────────────────────────────────────────────────────────────────

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
        showNotification(
            t('admin_files.download_error', 'Download error: {{message}}', { message: error.message }),
            'error',
        );
    }
}

// ── Delete ───────────────────────────────────────────────────────────────────

async function deleteAdminFile(filename) {
    if (!confirm(t('admin_files.delete_confirm', 'Delete file «{{name}}»?', { name: filename }))) return;

    try {
        const result = await adminFilesAPI.delete(filename);
        showNotification(
            t('admin_files.deleted', 'File deleted: {{message}}', { message: result.message || 'OK' }),
            'success',
        );
        await loadFiles();
    } catch (error) {
        if (error.status === 401 || error.status === 403) { REDIRECT_HOME(); return; }
        showNotification(
            t('admin_files.generic_error', 'Error: {{message}}', { message: error.message }),
            'error',
        );
    }
}

// ── System statistics ────────────────────────────────────────────────────────

export async function loadSystemStats() {
    await showSystemStats();

    const statsInfo = document.getElementById('statsInfo');
    if (!statsInfo) return;

    const wrap = createElement('div', { className: 'admin-stats-toolbar' });

    const btnDetailed = createElement('button', {
        className: 'btn-info',
        textContent: `📈 ${t('admin_files.btn_detailed', 'Detailed statistics')}`,
    });
    btnDetailed.addEventListener('click', showDetailedStats);
    wrap.appendChild(btnDetailed);

    const btnRefresh = createElement('button', {
        className: 'btn-secondary',
        textContent: `🔄 ${t('admin_files.btn_refresh', 'Refresh')}`,
    });
    btnRefresh.addEventListener('click', showSystemStats);
    wrap.appendChild(btnRefresh);

    statsInfo.appendChild(wrap);
}

export async function showSystemStats() {
    const statsInfo = document.getElementById('statsInfo');
    if (!statsInfo) return;

    statsInfo.innerHTML = `<div class="loading">⏳ ${t('admin_files.loading_stats', 'Loading statistics…')}</div>`;

    try {
        const data = await system.health();

        statsInfo.innerHTML = '';

        statsInfo.appendChild(createElement('h3', {
            textContent: `🩺 ${t('admin_files.system_status', 'System status')}`,
        }));
        statsInfo.appendChild(createElement('p', {
            textContent: t('admin_files.status_value', 'Status: {{value}}', { value: data.status || '—' }),
        }));
        statsInfo.appendChild(createElement('p', {
            textContent: t('admin_files.version_value', 'Version: {{value}}', { value: data.version || '—' }),
        }));

        statsInfo.appendChild(createElement('h4', {
            textContent: t('admin_files.features_heading', 'Features:'),
        }));
        const ulFeatures = document.createElement('ul');
        if (data.features) {
            Object.entries(data.features).forEach(([k, v]) => {
                ulFeatures.appendChild(createElement('li', { textContent: `${k}: ${v ? '✅' : '❌'}` }));
            });
        }
        statsInfo.appendChild(ulFeatures);

        statsInfo.appendChild(createElement('h4', {
            textContent: t('admin_files.directories_heading', 'Directories:'),
        }));
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
        showNotification(
            t('admin_files.generic_error', 'Error: {{message}}', { message: error.message }),
            'error',
        );
    }
}

// ── Cleanup statistics ───────────────────────────────────────────────────────

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

// ── Force purge ──────────────────────────────────────────────────────────────

export async function purgeAllFiles() {
    if (!confirm(`⚠️ ${t('admin_files.purge_confirm', 'Delete ALL encrypted files?\nIRREVERSIBLE!\n\nContinue?')}`)) return;
    if (prompt(t('admin_files.purge_prompt', 'Type "DELETE ALL" to confirm:')) !== 'DELETE ALL') {
        showNotification(t('admin_files.cancelled', 'Cancelled'), 'info');
        return;
    }

    try {
        const result = await adminFilesAPI.purge();
        showNotification(
            `✅ ${t('admin_files.purge_success', 'Deleted: temporary={{decrypted}}, encrypted={{encrypted}}', {
                decrypted: result.deleted.decrypted,
                encrypted: result.deleted.encrypted,
            })}`,
            'success'
        );
        if (result.errors?.length > 0) {
            showNotification(
                t('admin_files.purge_errors', 'Errors: {{errors}}', { errors: result.errors.join('; ') }),
                'warning',
            );
        }
        await loadFiles();
    } catch (error) {
        if (error.status === 401 || error.status === 403) { REDIRECT_HOME(); return; }
        showNotification(
            t('admin_files.generic_error', 'Error: {{message}}', { message: error.message }),
            'error',
        );
    }
}
