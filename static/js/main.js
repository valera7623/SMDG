// static/js/main.js
// Точка входа для пользовательской части (index.html)

import { initAuth, switchAuthTab, handleSetup2FA, logout } from './modules/auth.js';
import { initFiles, loadFileList, downloadFile, copyToClipboard, openOHIFViewer } from './modules/files.js';
import { showNotification } from './utils/notifications.js';
import './page-transitions.js';
import { initResponsiveUI } from './responsive.js';
import { bindThemeToggles, initTheme, setSmdgTheme } from './theme-init.js';

// ── Feature Flags (проверяем при загрузке страницы) ──────────────────────────
async function checkFeatureFlags() {
    try {
        const resp = await fetch('/health');
        if (resp.ok) {
            const data = await resp.json();
            window.__DICOM_VIEWER_ENABLED__ = !!data.features?.dicom_viewer;
            console.log('[Feature Flags] DICOM Viewer:', window.__DICOM_VIEWER_ENABLED__);
        }
    } catch (e) {
        console.warn('[Feature Flags] Не удалось проверить /health:', e);
        window.__DICOM_VIEWER_ENABLED__ = false;
    }
}

document.addEventListener('DOMContentLoaded', async () => {
    if (window.I18N && typeof window.I18N.init === 'function') {
        await window.I18N.init();
    }
    initTheme();
    bindThemeToggles();
    await checkFeatureFlags();
    initResponsiveUI();
    await initAuth();
    initFiles();
});

// ── Экспорт в window (для onclick-атрибутов в HTML) ──────────────────────────
// Рекомендация: в новых страницах используйте addEventListener вместо onclick.
// Эти экспорты поддерживают обратную совместимость с существующим HTML.

window.switchAuthTab   = switchAuthTab;
window.handleSetup2FA  = handleSetup2FA;
window.logout          = logout;
window.downloadFile    = downloadFile;
window.copyToClipboard = copyToClipboard;
window.loadFileList    = loadFileList;
window.showNotification = showNotification;

// Забытый пароль (заглушка — реализуйте по необходимости)
window.showForgotPassword = () => showNotification('Свяжитесь с администратором', 'info');
window.showTerms = () => alert('Условия использования системы SMDG');

/**
 * Нижнее toast-уведомление (не заменяет showNotification / #notificationContainer).
 * @param {string} message
 * @param {'info'|'success'|'error'|'warning'} [type='info']
 * @param {number} [ttlMs=3000]
 */
window.showToast = (message, type = 'info', ttlMs = 3000) => {
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    const span = document.createElement('span');
    span.textContent = message;
    toast.appendChild(span);
    document.body.appendChild(toast);
    window.setTimeout(() => {
        toast.remove();
    }, ttlMs);
};

/** Добавляет класс skeleton первому совпадению селектора. */
window.showSkeleton = (selector) => {
    const el = document.querySelector(selector);
    if (el) el.classList.add('skeleton');
};

window.hideSkeleton = (selector) => {
    const el = document.querySelector(selector);
    if (el) el.classList.remove('skeleton');
};

/** Опционально: confetti с CDN canvas-confetti (без ошибки, если скрипт не подключён). */
window.showConfetti = () => {
    if (typeof globalThis.confetti === 'function') {
        globalThis.confetti({ particleCount: 100, spread: 70, origin: { y: 0.6 } });
    }
};

window.setSmdgTheme = setSmdgTheme;