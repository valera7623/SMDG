// static/js/modules/admin-users.js

import { adminUsers as adminUsersAPI } from '../core/api.js';
import { showNotification }   from '../utils/notifications.js';
import { showConfirm }        from '../utils/modals.js';
import { createElement }      from '../utils/dom.js';
import { roleName }           from '../core/config.js';
import { t }                  from '../utils/i18n.js';
import {
    currentUser,
    selectedUsers, clearSelectedUsers,
    currentPage, setCurrentPage,
    pageSize, totalUsers, setTotalUsers,
    currentFilters, setFilters, resetFilters,
} from '../core/state.js';

import { redirectToLogin } from '../spa-nav.js';

const REDIRECT_HOME = () => redirectToLogin();

/**
 * Единая обработка ошибок API:
 * - при 401/403 → редирект на главную и возврат true (вызывающий должен выйти);
 * - иначе — показать toast и вернуть false.
 *
 * @param {Error & { status?: number }} error
 * @param {string} [fallbackKey='admin_users.generic_error']
 * @returns {boolean} true, если сработал редирект (вызывающий должен завершить обработчик).
 */
function handleApiError(error, fallbackKey = 'admin_users.generic_error') {
    if (error?.status === 401 || error?.status === 403) {
        REDIRECT_HOME();
        return true;
    }
    showNotification(
        t(fallbackKey, 'Error: {{message}}', { message: error?.message ?? '' }),
        'error',
    );
    return false;
}

// ── Statistics ───────────────────────────────────────────────────────────────

export async function loadUserStats() {
    try {
        const s = await adminUsersAPI.stats();
        _setText('totalUsers',  s.total_users);
        _setText('activeUsers', s.active_users);
        _setText('adminCount',  s.admins);
        _setText('doctorCount', s.doctors);
        _setText('userCount',   s.regular_users);
        _setText('twofaCount',  s.users_with_2fa);
    } catch (error) {
        if (error?.status === 401 || error?.status === 403) { REDIRECT_HOME(); return; }
        showNotification(t('admin_users.stats_error', 'Failed to load statistics'), 'error');
    }
}

function _setText(id, val) {
    const el = document.getElementById(id);
    if (el) el.textContent = val ?? 0;
}

// ── User list ────────────────────────────────────────────────────────────────

export async function loadUsers(resetPage = false) {
    if (resetPage) setCurrentPage(0);

    try {
        const { users, total } = await adminUsersAPI.list({
            skip:        currentPage * pageSize,
            limit:       pageSize,
            search:      currentFilters.search,
            role:        currentFilters.role,
            active_only: currentFilters.active_only,
        });

        setTotalUsers(total);
        renderUsersTable(users);
        renderPagination();

    } catch (error) {
        if (error?.status === 401 || error?.status === 403) { REDIRECT_HOME(); return; }
        const tbody = document.getElementById('usersTableBody');
        if (tbody) {
            tbody.innerHTML = '';
            const label = `❌ ${t('admin_users.error_prefix', 'Error: {{message}}', { message: error.message })}`;
            const td = _errorCell(label, 8);
            const tr = document.createElement('tr');
            tr.appendChild(td);
            tbody.appendChild(tr);
        }
    }
}

// ── Table rendering ──────────────────────────────────────────────────────────

export function renderUsersTable(users) {
    const tbody = document.getElementById('usersTableBody');
    if (!tbody) return;
    tbody.innerHTML = '';

    if (!users?.length) {
        const tr = document.createElement('tr');
        tr.appendChild(_errorCell(`📭 ${t('admin_users.empty_users', 'No users')}`, 8));
        tbody.appendChild(tr);
        return;
    }

    users.forEach(user => {
        const isMe = user.username === currentUser;
        tbody.appendChild(_createUserRow(user, isMe));
    });

    _syncSelectedCount();
}

function _createUserRow(user, isMe) {
    const tr = document.createElement('tr');

    const cb = document.createElement('input');
    cb.type      = 'checkbox';
    cb.className = 'user-checkbox';
    cb.value     = user.id;
    cb.disabled  = isMe;
    cb.addEventListener('change', _syncSelectedCount);
    const tdCb = document.createElement('td');
    tdCb.setAttribute('data-label', t('admin_users.col_select', 'Select'));
    tdCb.appendChild(cb);
    tr.appendChild(tdCb);

    tr.appendChild(_tdLabeled(String(user.id ?? ''), 'admin_users.col_id'));

    const tdUser = document.createElement('td');
    tdUser.setAttribute('data-label', t('admin_users.col_username', 'Username'));
    tdUser.appendChild(document.createTextNode(String(user.username ?? '')));
    if (isMe) {
        tdUser.appendChild(createElement('span', {
            textContent: t('admin_users.me_suffix', ' (you)'),
            style: { color: '#888' },
        }));
    }
    tr.appendChild(tdUser);

    tr.appendChild(_tdLabeled(user.email || '', 'admin_users.col_email'));

    const roleSpan = createElement('span', { className: `role-badge ${user.role}`,
        textContent: roleName(user.role) });
    const tdRole = document.createElement('td');
    tdRole.setAttribute('data-label', t('admin_users.col_role', 'Role'));
    tdRole.appendChild(roleSpan);
    tr.appendChild(tdRole);

    const statusSpan = createElement('span', {
        className:   `status-badge ${user.is_active ? 'active' : 'inactive'}`,
        textContent: user.is_active
            ? t('admin_users.status_active', 'Active')
            : t('admin_users.status_inactive', 'Inactive'),
    });
    const tdStatus = document.createElement('td');
    tdStatus.setAttribute('data-label', t('admin_users.col_status', 'Status'));
    tdStatus.appendChild(statusSpan);
    tr.appendChild(tdStatus);

    const has2FA = Boolean(user.has_2fa);
    const twofaSpan = createElement('span', {
        className:   `twofa-badge ${has2FA ? 'enabled' : 'disabled'}`,
        title:        has2FA
            ? t('admin_users.twofa_on_title', '2FA enabled')
            : t('admin_users.twofa_off_title', '2FA disabled'),
        textContent:  has2FA ? '✅' : '❌',
    });
    const td2fa = document.createElement('td');
    td2fa.setAttribute('data-label', t('admin_users.col_2fa', '2FA'));
    td2fa.appendChild(twofaSpan);
    tr.appendChild(td2fa);

    const wrap = createElement('div', { className: 'action-buttons' });

    const mkBtn = (cls, label, handler, disabled = false) => {
        const btn = createElement('button', { className: `action-btn ${cls}`, textContent: label });
        btn.disabled = disabled;
        btn.addEventListener('click', handler);
        return btn;
    };

    wrap.appendChild(mkBtn('edit',           '✏️',  () => editUser(user.id),                  isMe));
    wrap.appendChild(mkBtn('reset-password', '🔑',  () => resetPassword(user.id, user.username), isMe));
    wrap.appendChild(mkBtn('reset-2fa',      '🔐',  () => reset2FA(user.id, user.username),    isMe || !has2FA));
    wrap.appendChild(mkBtn('delete',         '🗑️', () => deleteUser(user.id, user.username),   isMe));

    const tdActions = document.createElement('td');
    tdActions.setAttribute('data-label', t('admin_users.col_actions', 'Actions'));
    tdActions.appendChild(wrap);
    tr.appendChild(tdActions);

    return tr;
}

function _tdLabeled(text, labelKey) {
    const td = document.createElement('td');
    td.setAttribute('data-label', t(labelKey, labelKey));
    td.textContent = String(text ?? '');
    return td;
}

function _errorCell(text, colspan) {
    const td = createElement('td', { className: 'empty', textContent: text });
    td.colSpan = colspan;
    return td;
}

// ── Pagination ───────────────────────────────────────────────────────────────

export function renderPagination() {
    const pagination = document.getElementById('pagination');
    if (!pagination) return;
    pagination.innerHTML = '';

    const totalPages = Math.ceil(totalUsers / pageSize);
    if (totalPages <= 1) return;

    const mkPageBtn = (label, page, disabled = false, active = false) => {
        const btn = createElement('button', { className: `page-btn${active ? ' active' : ''}`, textContent: String(label) });
        btn.disabled = disabled;
        if (!disabled) btn.addEventListener('click', () => _changePage(page));
        return btn;
    };

    pagination.appendChild(mkPageBtn('←', currentPage - 1, currentPage === 0));

    for (let i = 0; i < totalPages; i++) {
        const show = i === 0 || i === totalPages - 1 || (i >= currentPage - 2 && i <= currentPage + 2);
        const dots = i === currentPage - 3 || i === currentPage + 3;
        if (show) {
            pagination.appendChild(mkPageBtn(i + 1, i, false, i === currentPage));
        } else if (dots) {
            pagination.appendChild(createElement('span', { className: 'page-dots', textContent: '…' }));
        }
    }

    pagination.appendChild(mkPageBtn('→', currentPage + 1, currentPage >= totalPages - 1));
}

function _changePage(page) {
    if (page < 0 || page >= Math.ceil(totalUsers / pageSize)) return;
    setCurrentPage(page);
    loadUsers();
}

// ── Filters ──────────────────────────────────────────────────────────────────

export function applyFilters() {
    setFilters({
        search:      document.getElementById('searchInput')?.value ?? '',
        role:        document.getElementById('roleFilter')?.value ?? '',
        active_only: document.getElementById('statusFilter')?.value === 'active',
    });
    loadUsers(true);
}

export function clearFilters() {
    const searchInput  = document.getElementById('searchInput');
    const roleFilter   = document.getElementById('roleFilter');
    const statusFilter = document.getElementById('statusFilter');
    if (searchInput)  searchInput.value  = '';
    if (roleFilter)   roleFilter.value   = '';
    if (statusFilter) statusFilter.value = '';
    resetFilters();
    loadUsers(true);
}

let _searchTimeout;
export function debounceSearch() {
    clearTimeout(_searchTimeout);
    _searchTimeout = setTimeout(applyFilters, 500);
}

// ── Selection ────────────────────────────────────────────────────────────────

export function toggleAllCheckboxes() {
    const selectAll  = document.getElementById('selectAllCheckbox');
    const checkboxes = document.querySelectorAll('.user-checkbox:not(:disabled)');
    clearSelectedUsers();
    checkboxes.forEach(cb => {
        cb.checked = selectAll.checked;
        if (selectAll.checked) selectedUsers.add(parseInt(cb.value));
    });
    _syncSelectedCount();
}

export function selectAll() {
    const checkboxes = document.querySelectorAll('.user-checkbox:not(:disabled)');
    clearSelectedUsers();
    checkboxes.forEach(cb => { cb.checked = true; selectedUsers.add(parseInt(cb.value)); });
    _syncSelectedCount();
}

export function clearSelection() {
    clearSelectedUsers();
    document.querySelectorAll('.user-checkbox').forEach(cb => cb.checked = false);
    const selectAll = document.getElementById('selectAllCheckbox');
    if (selectAll) { selectAll.checked = false; selectAll.indeterminate = false; }
    _syncSelectedCount();
}

function _syncSelectedCount() {
    const checkboxes = document.querySelectorAll('.user-checkbox:checked');
    clearSelectedUsers();
    checkboxes.forEach(cb => selectedUsers.add(parseInt(cb.value)));

    const countEl = document.getElementById('selectedCount');
    if (countEl) {
        countEl.textContent = t('admin_users.selected', 'Selected: {{count}}', { count: selectedUsers.size });
    }

    const total   = document.querySelectorAll('.user-checkbox:not(:disabled)').length;
    const checked = checkboxes.length;
    const masterCb = document.getElementById('selectAllCheckbox');
    if (masterCb) {
        masterCb.checked       = checked === total && total > 0;
        masterCb.indeterminate = checked > 0 && checked < total;
    }

    const bulkCtrl = document.querySelector('.bulk-controls');
    bulkCtrl?.classList.toggle('has-selection', selectedUsers.size > 0);
}

// ── Bulk actions ─────────────────────────────────────────────────────────────

export async function executeBulkAction() {
    const action = document.getElementById('bulkActionSelect')?.value;
    if (!action) {
        showNotification(t('admin_users.select_action', 'Select an action'), 'warning');
        return;
    }
    if (selectedUsers.size === 0) {
        showNotification(t('admin_users.select_users_first', 'Select users'), 'warning');
        return;
    }

    let role = null;
    let msg  = '';
    const count = selectedUsers.size;

    if (action === 'activate') {
        msg = t('admin_users.confirm_activate', 'Activate {{count}} user(s)?', { count });
    } else if (action === 'deactivate') {
        msg = t('admin_users.confirm_deactivate', 'Deactivate {{count}} user(s)?', { count });
    } else if (action === 'change_role') {
        role = document.getElementById('bulkRoleSelect')?.value;
        if (!role) {
            showNotification(t('admin_users.select_new_role', 'Select a new role'), 'warning');
            return;
        }
        msg = t('admin_users.confirm_change_role',
            'Change role of {{count}} user(s) to «{{role}}»?',
            { count, role: roleName(role) },
        );
    } else if (action === 'delete') {
        msg = `⚠️ ${t('admin_users.confirm_delete_bulk', 'DELETE {{count}} user(s)? This is irreversible!', { count })}`;
    } else {
        return;
    }

    showConfirm(msg, async () => {
        try {
            const result = await adminUsersAPI.bulk(action, Array.from(selectedUsers), role);
            showNotification(
                t('admin_users.bulk_done', '{{message}} — {{count}} updated', {
                    message: result.message || t('admin_users.bulk_done_default', 'Done'),
                    count:   result.affected ?? count,
                }),
                'success'
            );
            clearSelection();
            await loadUsers();
            await loadUserStats();
        } catch (error) {
            handleApiError(error);
        }
    });
}

// ── CRUD ─────────────────────────────────────────────────────────────────────

export function showCreateUserModal() {
    document.getElementById('modalTitle').textContent =
        `➕ ${t('admin_users.modal_create_header', 'Create user')}`;
    document.getElementById('userId').value           = '';
    document.getElementById('modalUsername').value    = '';
    document.getElementById('modalUsername').disabled  = false;
    document.getElementById('modalEmail').value        = '';
    document.getElementById('modalPassword').value     = '';
    document.getElementById('modalPassword').required  = true;
    document.getElementById('modalRole').value         = 'user';
    document.getElementById('modalIsActive').checked   = true;
    document.getElementById('reset2faGroup').style.display = 'none';
    document.getElementById('modalSubmitBtn').textContent  = t('admin_users.btn_create', 'Create');
    document.getElementById('userModal').style.display     = 'block';
}

export async function editUser(userId) {
    try {
        const user = await adminUsersAPI.get(userId);

        document.getElementById('modalTitle').textContent    =
            `✏️ ${t('admin_users.modal_edit_header', 'Edit')}`;
        document.getElementById('userId').value              = user.id;
        document.getElementById('modalUsername').value       = user.username;
        document.getElementById('modalUsername').disabled     = true;
        document.getElementById('modalEmail').value          = user.email;
        document.getElementById('modalPassword').value       = '';
        document.getElementById('modalPassword').required    = false;
        document.getElementById('modalRole').value           = user.role;
        document.getElementById('modalIsActive').checked     = user.is_active;
        document.getElementById('reset2faGroup').style.display = user.has_2fa ? 'block' : 'none';
        document.getElementById('modalReset2fa').checked     = false;
        document.getElementById('modalSubmitBtn').textContent = t('admin_users.btn_save', 'Save');
        document.getElementById('userModal').style.display   = 'block';

    } catch (error) {
        handleApiError(error);
    }
}

export function closeUserModal() {
    document.getElementById('userModal').style.display = 'none';
    document.getElementById('modalUsername').disabled  = false;
}

export async function handleUserSubmit(event) {
    event.preventDefault();

    const userId = document.getElementById('userId').value;
    const isEdit = !!userId;

    const username   = document.getElementById('modalUsername').value.trim();
    const email      = document.getElementById('modalEmail').value.trim();
    const role       = document.getElementById('modalRole').value;
    const is_active  = document.getElementById('modalIsActive').checked;
    const passwordEl = document.getElementById('modalPassword');
    const password   = passwordEl.value;

    if (!username || username.length < 3 || username.length > 50 || !/^[a-zA-Z0-9_]+$/.test(username)) {
        showNotification(t('admin_users.validate_username', 'Username: 3–50 characters, letters/digits/_'), 'error');
        return;
    }
    if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
        showNotification(t('admin_users.validate_email', 'Invalid email format'), 'error');
        return;
    }

    const formData = { username, email, role, is_active };

    if (!isEdit) {
        if (!password) {
            showNotification(t('admin_users.enter_password', 'Enter a password'), 'error');
            return;
        }
        if (password.length < 8) {
            showNotification(t('admin_users.password_min', 'Password must be at least 8 characters'), 'error');
            return;
        }
        formData.password = password;
    } else {
        if (password) {
            if (password.length < 8) {
                showNotification(t('admin_users.password_min', 'Password must be at least 8 characters'), 'error');
                return;
            }
            formData.reset_password = true;
            formData.new_password   = password;
        }
        if (document.getElementById('modalReset2fa')?.checked) {
            formData.reset_2fa = true;
        }
    }

    try {
        if (isEdit) {
            await adminUsersAPI.update(userId, formData);
        } else {
            await adminUsersAPI.create(formData);
        }
        showNotification(
            isEdit
                ? t('admin_users.updated', 'User updated')
                : t('admin_users.created', 'User created'),
            'success',
        );
        closeUserModal();
        await loadUsers();
        await loadUserStats();
    } catch (error) {
        handleApiError(error);
    }
}

export function resetPassword(userId, username) {
    showConfirm(
        t('admin_users.confirm_reset_pw', 'Reset password for user {{username}}?', { username }),
        async () => {
            const newPassword = prompt(
                t('admin_users.prompt_new_pw', 'Enter a new password (at least 8 characters):'),
            );
            if (!newPassword || newPassword.length < 8) {
                showNotification(
                    t('admin_users.password_min', 'Password must be at least 8 characters'),
                    'error',
                );
                return;
            }
            try {
                await adminUsersAPI.resetPassword(userId, newPassword);
                showNotification(
                    t('admin_users.pw_reset', 'Password for {{username}} has been reset', { username }),
                    'success',
                );
            } catch (error) {
                handleApiError(error);
            }
        },
    );
}

export function reset2FA(userId, username) {
    showConfirm(
        t('admin_users.confirm_reset_2fa', 'Reset 2FA for {{username}}?', { username }),
        async () => {
            try {
                await adminUsersAPI.update(userId, { reset_2fa: true });
                showNotification(
                    t('admin_users.twofa_reset', '2FA for {{username}} has been reset', { username }),
                    'success',
                );
                await loadUsers();
            } catch (error) {
                handleApiError(error);
            }
        },
    );
}

export function deleteUser(userId, username) {
    showConfirm(
        `⚠️ ${t('admin_users.confirm_delete', 'DELETE user {{username}}? This is irreversible!', { username })}`,
        async () => {
            try {
                await adminUsersAPI.delete(userId);
                showNotification(
                    t('admin_users.deleted', 'User {{username}} deleted', { username }),
                    'success',
                );
                await loadUsers();
                await loadUserStats();
            } catch (error) {
                handleApiError(error);
            }
        },
    );
}

// ── Logout ───────────────────────────────────────────────────────────────────

export async function logout() {
    if (!confirm(t('admin_users.confirm_logout', 'Are you sure?'))) return;
    try {
        const { auth: authAPI } = await import('../core/api.js');
        const res = await authAPI.logout();
        if (res.ok) redirectToLogin();
        else showNotification(t('admin_users.logout_error', 'Logout error'), 'error');
    } catch (e) {
        showNotification(
            t('admin_users.generic_error', 'Error: {{message}}', { message: e.message }),
            'error',
        );
    }
}
