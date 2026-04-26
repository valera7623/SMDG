// static/js/admin.js
// Точка входа для страницы администратора (admin.html)

import {
    loadFiles,
    loadSystemStats,
    getCleanupStats,
    purgeAllFiles,
} from './modules/admin-files.js';
import { initResponsiveUI } from './responsive.js';

document.addEventListener('DOMContentLoaded', () => {
    initResponsiveUI();
    loadFiles();
    loadSystemStats();
});

// Re-render when the active language changes so dynamically generated
// buttons, headings and list entries pick up the new strings.
window.addEventListener('i18n:updated', () => {
    loadFiles();
    loadSystemStats();
});

// ── Экспорт в window (для onclick-атрибутов в admin.html) ────────────────────
window.loadFiles        = loadFiles;
window.getCleanupStats  = getCleanupStats;
window.purgeAllFiles    = purgeAllFiles;