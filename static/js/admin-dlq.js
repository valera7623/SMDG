import {
    applyFilters,
    clearFilters,
    cleanupOld,
    deleteMessage,
    loadMessages,
    loadStats,
    nextPage,
    prevPage,
    replayMessage,
    viewMessage,
} from "./modules/admin-dlq.js";
import "./page-transitions.js";
import { initResponsiveUI } from "./responsive.js";
import { bindThemeToggles, initTheme } from "./theme-init.js";

document.addEventListener("DOMContentLoaded", async () => {
    if (window.I18N && typeof window.I18N.init === "function") {
        await window.I18N.init();
    }
    initTheme();
    bindThemeToggles();
    initResponsiveUI();
    const search = document.getElementById("messageIdSearch");
    const limit = document.getElementById("limitFilter");
    if (search) {
        search.addEventListener("keydown", (event) => {
            if (event.key === "Enter") {
                event.preventDefault();
                applyFilters();
            }
        });
    }
    if (limit) {
        limit.addEventListener("change", () => applyFilters());
    }

    await loadStats();
    await loadMessages();

    window.addEventListener("i18n:updated", () => {
        void loadStats();
        void loadMessages();
    });

    window.__dlqRefreshTimer = window.setInterval(async () => {
        try {
            await Promise.all([loadStats(), loadMessages()]);
        } catch {
            // Keep timer alive; page may briefly fail during deploy/restart.
        }
    }, 10000);
});

window.loadMessages = loadMessages;
window.applyFilters = applyFilters;
window.viewMessage = viewMessage;
window.replayMessage = replayMessage;
window.deleteMessage = deleteMessage;
window.cleanupOld = cleanupOld;
window.clearFilters = clearFilters;
window.nextPage = nextPage;
window.prevPage = prevPage;
