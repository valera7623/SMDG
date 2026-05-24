// static/js/admin-users.js
// Точка входа для страницы управления пользователями (admin_users.html)

import {
    loadUserStats,
    loadUsers,
    applyFilters,
    clearFilters,
    debounceSearch,
    toggleAllCheckboxes,
    selectAll,
    clearSelection,
    executeBulkAction,
    showCreateUserModal,
    editUser,
    closeUserModal,
    handleUserSubmit,
    resetPassword,
    reset2FA,
    deleteUser,
    logout,
} from './modules/admin-users.js';

import { confirmAction, closeConfirmModal } from './utils/modals.js';
import './page-transitions.js';
import { initResponsiveUI } from './responsive.js';
import { bindThemeToggles, initTheme } from './theme-init.js';
import { auth as authAPI } from './core/api.js';
import { setCurrentUser } from './core/state.js';

document.addEventListener('DOMContentLoaded', async () => {
    if (window.I18N && typeof window.I18N.init === 'function') {
        await window.I18N.init();
    }
    initTheme();
    bindThemeToggles();
    initResponsiveUI();
    try {
        const currentAdmin = await authAPI.whoami();
        setCurrentUser(currentAdmin.sub);
        const usernameEl = document.getElementById('currentAdminUsername');
        if (usernameEl) usernameEl.textContent = currentAdmin.sub;
    } catch (error) {
        if (error?.status === 401 || error?.status === 403) {
            window.location.href = '/';
            return;
        }
        throw error;
    }
    await loadUserStats();
    await loadUsers();

    // Показать/скрыть select роли при bulk change_role
    const bulkActionSelect = document.getElementById('bulkActionSelect');
    const bulkRoleSelect   = document.getElementById('bulkRoleSelect');
    if (bulkActionSelect && bulkRoleSelect) {
        bulkActionSelect.addEventListener('change', () => {
            bulkRoleSelect.style.display =
                bulkActionSelect.value === 'change_role' ? 'inline-block' : 'none';
        });
    }

    // Форма пользователя — вешаем через addEventListener
    document.getElementById('userForm')
        ?.addEventListener('submit', handleUserSubmit);
});

// Re-render the user table and stats when the active language changes.
window.addEventListener('i18n:updated', () => {
    loadUserStats();
    loadUsers();
});

// ── Экспорт в window (для onclick-атрибутов в admin_users.html) ───────────────
window.loadUsers           = loadUsers;
window.applyFilters        = applyFilters;
window.clearFilters        = clearFilters;
window.debounceSearch      = debounceSearch;
window.toggleAllCheckboxes = toggleAllCheckboxes;
window.selectAll           = selectAll;
window.clearSelection      = clearSelection;
window.executeBulkAction   = executeBulkAction;
window.showCreateUserModal = showCreateUserModal;
window.editUser            = editUser;
window.closeUserModal      = closeUserModal;
window.handleUserSubmit    = handleUserSubmit;
window.resetPassword       = resetPassword;
window.reset2FA            = reset2FA;
window.deleteUser          = deleteUser;
window.logout              = logout;
window.confirmAction       = confirmAction;
window.closeConfirmModal   = closeConfirmModal;