// static/js/admin.js
// Точка входа для страницы администратора (admin.html)

import {
    loadFiles,
    loadSystemStats,
    getCleanupStats,
    purgeAllFiles,
} from './modules/admin-files.js';

document.addEventListener('DOMContentLoaded', () => {
    loadFiles();
    loadSystemStats();
});

// ── Экспорт в window (для onclick-атрибутов в admin.html) ────────────────────
window.loadFiles        = loadFiles;
window.getCleanupStats  = getCleanupStats;
window.purgeAllFiles    = purgeAllFiles;