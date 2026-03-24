// static/js/modules/admin-users.js

import { adminUsers as adminUsersAPI } from '../core/api.js';
import { showNotification }   from '../utils/notifications.js';
import { showConfirm }        from '../utils/modals.js';
import { createElement }      from '../utils/dom.js';
import { ROLE_NAMES }         from '../core/config.js';
import {
    currentUser,
    selectedUsers, clearSelectedUsers,
    currentPage, setCurrentPage,
    pageSize, totalUsers, setTotalUsers,
    currentFilters, setFilters, resetFilters,
} from '../core/state.js';

const REDIRECT_HOME = () => { window.location.href = '/'; };

// ── Статистика ────────────────────────────────────────────────────────────────

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
        if (error.status === 401 || error.status === 403) { REDIRECT_HOME(); return; }
        showNotification('Ошибка загрузки статистики', 'error');
    }
}

function _setText(id, val) {
    const el = document.getElementById(id);
    if (el) el.textContent = val ?? 0;
}

// ── Список пользователей ──────────────────────────────────────────────────────

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
        if (error.status === 401 || error.status === 403) { REDIRECT_HOME(); return; }
        const tbody = document.getElementById('usersTableBody');
        if (tbody) {
            tbody.innerHTML = '';
            const td = _errorCell(`❌ Ошибка: ${error.message}`, 8);
            const tr = document.createElement('tr');
            tr.appendChild(td);
            tbody.appendChild(tr);
        }
    }
}

// ── Рендер таблицы ────────────────────────────────────────────────────────────

export function renderUsersTable(users) {
    const tbody = document.getElementById('usersTableBody');
    if (!tbody) return;
    tbody.innerHTML = '';

    if (!users?.length) {
        const tr = document.createElement('tr');
        tr.appendChild(_errorCell('📭 Нет пользователей', 8));
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

    // Чекбокс
    const cb = document.createElement('input');
    cb.type      = 'checkbox';
    cb.className = 'user-checkbox';
    cb.value     = user.id;
    cb.disabled  = isMe;
    cb.addEventListener('change', _syncSelectedCount);
    const tdCb = document.createElement('td');
    tdCb.appendChild(cb);
    tr.appendChild(tdCb);

    // ID
    tr.appendChild(_td(user.id));

    // Username
    const tdUser = _td(user.username);
    if (isMe) tdUser.appendChild(createElement('span', { textContent: ' (вы)', style: { color: '#888' } }));
    tr.appendChild(tdUser);

    // Email
    tr.appendChild(_td(user.email || ''));

    // Роль
    const roleSpan = createElement('span', { className: `role-badge ${user.role}`,
        textContent: ROLE_NAMES[user.role] || user.role });
    const tdRole = document.createElement('td');
    tdRole.appendChild(roleSpan);
    tr.appendChild(tdRole);

    // Статус
    const statusSpan = createElement('span', {
        className:   `status-badge ${user.is_active ? 'active' : 'inactive'}`,
        textContent: user.is_active ? 'Активен' : 'Неактивен',
    });
    const tdStatus = document.createElement('td');
    tdStatus.appendChild(statusSpan);
    tr.appendChild(tdStatus);

    // 2FA
    const twofaSpan = createElement('span', {
        className:   `twofa-badge ${user.otp_secret ? 'enabled' : 'disabled'}`,
        title:        user.otp_secret ? '2FA включена' : '2FA отключена',
        textContent:  user.otp_secret ? '✅' : '❌',
    });
    const td2fa = document.createElement('td');
    td2fa.appendChild(twofaSpan);
    tr.appendChild(td2fa);

    // Кнопки
    const wrap = createElement('div', { className: 'action-buttons' });

    const mkBtn = (cls, label, handler, disabled = false) => {
        const btn = createElement('button', { className: `action-btn ${cls}`, textContent: label });
        btn.disabled = disabled;
        btn.addEventListener('click', handler);
        return btn;
    };

    wrap.appendChild(mkBtn('edit',           '✏️',  () => editUser(user.id),                  isMe));
    wrap.appendChild(mkBtn('reset-password', '🔑',  () => resetPassword(user.id, user.username), isMe));
    wrap.appendChild(mkBtn('reset-2fa',      '🔐',  () => reset2FA(user.id, user.username),    isMe || !user.otp_secret));
    wrap.appendChild(mkBtn('delete',         '🗑️', () => deleteUser(user.id, user.username),   isMe));

    const tdActions = document.createElement('td');
    tdActions.appendChild(wrap);
    tr.appendChild(tdActions);

    return tr;
}

function _td(text) {
    return createElement('td', { textContent: String(text ?? '') });
}

function _errorCell(text, colspan) {
    const td = createElement('td', { className: 'empty', textContent: text });
    td.colSpan = colspan;
    return td;
}

// ── Пагинация ─────────────────────────────────────────────────────────────────

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

// ── Фильтры ───────────────────────────────────────────────────────────────────

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

// ── Выбор пользователей ───────────────────────────────────────────────────────

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
    if (countEl) countEl.textContent = `Выбрано: ${selectedUsers.size}`;

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

// ── Массовые действия ─────────────────────────────────────────────────────────

export async function executeBulkAction() {
    const action = document.getElementById('bulkActionSelect')?.value;
    if (!action) { showNotification('Выберите действие', 'warning'); return; }
    if (selectedUsers.size === 0) { showNotification('Выберите пользователей', 'warning'); return; }

    let role = null;
    let msg  = '';

    if (action === 'activate')       msg = `Активировать ${selectedUsers.size} пользователей?`;
    else if (action === 'deactivate') msg = `Деактивировать ${selectedUsers.size} пользователей?`;
    else if (action === 'change_role') {
        role = document.getElementById('bulkRoleSelect')?.value;
        if (!role) { showNotification('Выберите новую роль', 'warning'); return; }
        msg = `Изменить роль ${selectedUsers.size} пользователей на «${ROLE_NAMES[role]}»?`;
    } else if (action === 'delete') {
        msg = `⚠️ УДАЛИТЬ ${selectedUsers.size} пользователей? Это необратимо!`;
    } else return;

    showConfirm(msg, async () => {
        try {
            const result = await adminUsersAPI.bulk(action, Array.from(selectedUsers), role);
            showNotification(
                `${result.message || 'Выполнено'} — изменено ${result.affected ?? selectedUsers.size}`,
                'success'
            );
            clearSelection();
            await loadUsers();
            await loadUserStats();
        } catch (error) {
            if (error.status === 401 || error.status === 403) { REDIRECT_HOME(); return; }
            showNotification(`Ошибка: ${error.message}`, 'error');
        }
    });
}

// ── CRUD ──────────────────────────────────────────────────────────────────────

export function showCreateUserModal() {
    document.getElementById('modalTitle').textContent = '➕ Создание пользователя';
    document.getElementById('userId').value           = '';
    document.getElementById('modalUsername').value    = '';
    document.getElementById('modalUsername').disabled  = false;
    document.getElementById('modalEmail').value        = '';
    document.getElementById('modalPassword').value     = '';
    document.getElementById('modalPassword').required  = true;
    document.getElementById('modalRole').value         = 'user';
    document.getElementById('modalIsActive').checked   = true;
    document.getElementById('reset2faGroup').style.display = 'none';
    document.getElementById('modalSubmitBtn').textContent  = 'Создать';
    document.getElementById('userModal').style.display     = 'block';
}

export async function editUser(userId) {
    try {
        const user = await adminUsersAPI.get(userId);

        document.getElementById('modalTitle').textContent    = '✏️ Редактирование';
        document.getElementById('userId').value              = user.id;
        document.getElementById('modalUsername').value       = user.username;
        document.getElementById('modalUsername').disabled     = true;
        document.getElementById('modalEmail').value          = user.email;
        document.getElementById('modalPassword').value       = '';
        document.getElementById('modalPassword').required    = false;
        document.getElementById('modalRole').value           = user.role;
        document.getElementById('modalIsActive').checked     = user.is_active;
        document.getElementById('reset2faGroup').style.display = user.otp_secret ? 'block' : 'none';
        document.getElementById('modalReset2fa').checked     = false;
        document.getElementById('modalSubmitBtn').textContent = 'Сохранить';
        document.getElementById('userModal').style.display   = 'block';

    } catch (error) {
        if (error.status === 401 || error.status === 403) { REDIRECT_HOME(); return; }
        showNotification(`Ошибка: ${error.message}`, 'error');
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

    // Валидация
    if (!username || username.length < 3 || username.length > 50 || !/^[a-zA-Z0-9_]+$/.test(username)) {
        showNotification('Логин: 3–50 символов, буквы/цифры/_', 'error'); return;
    }
    if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
        showNotification('Неверный формат email', 'error'); return;
    }

    const formData = { username, email, role, is_active };

    if (!isEdit) {
        if (!password) { showNotification('Введите пароль', 'error'); return; }
        if (password.length < 8) { showNotification('Пароль минимум 8 символов', 'error'); return; }
        formData.password = password;
    } else {
        if (password) {
            if (password.length < 8) { showNotification('Пароль минимум 8 символов', 'error'); return; }
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
        showNotification(isEdit ? 'Пользователь обновлён' : 'Пользователь создан', 'success');
        closeUserModal();
        await loadUsers();
        await loadUserStats();
    } catch (error) {
        if (error.status === 401 || error.status === 403) { REDIRECT_HOME(); return; }
        showNotification(`Ошибка: ${error.message}`, 'error');
    }
}

export function resetPassword(userId, username) {
    showConfirm(`Сбросить пароль пользователя ${username}?`, async () => {
        const newPassword = prompt('Введите новый пароль (минимум 8 символов):');
        if (!newPassword || newPassword.length < 8) {
            showNotification('Пароль должен быть минимум 8 символов', 'error'); return;
        }
        try {
            await adminUsersAPI.resetPassword(userId, newPassword);
            showNotification(`Пароль пользователя ${username} сброшен`, 'success');
        } catch (error) {
            if (error.status === 401 || error.status === 403) { REDIRECT_HOME(); return; }
            showNotification(`Ошибка: ${error.message}`, 'error');
        }
    });
}

export function reset2FA(userId, username) {
    showConfirm(`Сбросить 2FA для ${username}?`, async () => {
        try {
            await adminUsersAPI.update(userId, { reset_2fa: true });
            showNotification(`2FA для ${username} сброшена`, 'success');
            await loadUsers();
        } catch (error) {
            if (error.status === 401 || error.status === 403) { REDIRECT_HOME(); return; }
            showNotification(`Ошибка: ${error.message}`, 'error');
        }
    });
}

export function deleteUser(userId, username) {
    showConfirm(`⚠️ УДАЛИТЬ пользователя ${username}? Это необратимо!`, async () => {
        try {
            await adminUsersAPI.delete(userId);
            showNotification(`Пользователь ${username} удалён`, 'success');
            await loadUsers();
            await loadUserStats();
        } catch (error) {
            if (error.status === 401 || error.status === 403) { REDIRECT_HOME(); return; }
            showNotification(`Ошибка: ${error.message}`, 'error');
        }
    });
}

// ── Logout ────────────────────────────────────────────────────────────────────

export async function logout() {
    if (!confirm('Вы уверены?')) return;
    try {
        const { auth: authAPI } = await import('../core/api.js');
        const res = await authAPI.logout();
        if (res.ok) window.location.href = '/';
        else showNotification('Ошибка выхода', 'error');
    } catch (e) {
        showNotification('Ошибка: ' + e.message, 'error');
    }
}