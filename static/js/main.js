// static/js/main.js
// Точка входа для пользовательской части (index.html)

import { initAuth, switchAuthTab, handleSetup2FA, logout } from './modules/auth.js';
import { initFiles, loadFileList, downloadFile, copyToClipboard, openOHIFViewer } from './modules/files.js';
import { showNotification } from './utils/notifications.js';
import { initResponsiveUI } from './responsive.js';

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
    await checkFeatureFlags();
    initResponsiveUI();
    initAuth();
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