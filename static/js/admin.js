// static/js/admin.js
// Точка входа для страницы администратора (admin.html)

import {
    loadFiles,
    loadSystemStats,
    getCleanupStats,
    purgeAllFiles,
} from './modules/admin-files.js';
import { initFileAudit, loadFileAuditEvents } from './modules/admin-file-audit.js';
import './page-transitions.js';
import { initResponsiveUI } from './responsive.js';
import { bindThemeToggles, initTheme } from './theme-init.js';

document.addEventListener('DOMContentLoaded', async () => {
    if (window.I18N && typeof window.I18N.init === 'function') {
        await window.I18N.init();
    }
    initTheme();
    bindThemeToggles();
    initResponsiveUI();
    loadFiles();
    loadSystemStats();
    initFileAudit();
});

// Re-render when the active language changes so dynamically generated
// buttons, headings and list entries pick up the new strings.
window.addEventListener('i18n:updated', () => {
    loadFiles();
    loadSystemStats();
    loadFileAuditEvents();
});

// ── Экспорт в window (для onclick-атрибутов в admin.html) ────────────────────
window.loadFiles        = loadFiles;
window.getCleanupStats  = getCleanupStats;
window.purgeAllFiles    = purgeAllFiles;
window.loadFileAuditEvents = loadFileAuditEvents;