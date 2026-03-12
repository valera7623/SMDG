// static/js/admin-users.js

const API_BASE = '/api';

let currentUser = null;
let selectedUsers = new Set();
let currentPage = 0;
let pageSize = 10;
let totalUsers = 0;
let currentFilters = {
    search: '',
    role: '',
    active_only: false
};
let actionCallback = null;

// ==================== Инициализация ====================

document.addEventListener('DOMContentLoaded', async function () {
    // Пробуем сразу загрузить данные
    // Если не авторизованы — backend вернёт 401 → редирект на главную
    await loadUserStats();
    await loadUsers();
});

// ==================== Загрузка статистики ====================

async function loadUserStats() {
    try {
        const response = await fetch(`${API_BASE}/admin/users/stats/overview`, {
            credentials: 'include'
        });

        if (!response.ok) {
            if (response.status === 401 || response.status === 403) {
                window.location.href = '/';
                return;
            }
            throw new Error(`Ошибка: ${response.status}`);
        }

        const stats = await response.json();

        document.getElementById('totalUsers').textContent = stats.total_users;
        document.getElementById('activeUsers').textContent = stats.active_users;
        document.getElementById('adminCount').textContent = stats.admins;
        document.getElementById('doctorCount').textContent = stats.doctors;
        document.getElementById('userCount').textContent = stats.regular_users;
        document.getElementById('twofaCount').textContent = stats.users_with_2fa;

    } catch (error) {
        console.error('Ошибка загрузки статистики:', error);
        showNotification('Ошибка загрузки статистики', 'error');
    }
}

// ==================== Загрузка пользователей ====================

async function loadUsers(resetPage = false) {
    if (resetPage) {
        currentPage = 0;
    }

    const skip = currentPage * pageSize;

    let url = `${API_BASE}/admin/users/?skip=${skip}&limit=${pageSize}`;

    if (currentFilters.search) {
        url += `&search=${encodeURIComponent(currentFilters.search)}`;
    }

    if (currentFilters.role) {
        url += `&role=${currentFilters.role}`;
    }

    if (currentFilters.active_only) {
        url += `&active_only=true`;
    }

    try {
        const response = await fetch(url, {
            credentials: 'include'
        });

        if (!response.ok) {
            if (response.status === 401 || response.status === 403) {
                window.location.href = '/';
                return;
            }
            throw new Error(`Ошибка: ${response.status}`);
        }

        const users = await response.json();

        // Пагинация через заголовок X-Total-Count
        const totalCount = response.headers.get('X-Total-Count') || users.length;
        totalUsers = parseInt(totalCount);

        // ← Вот здесь была проблема — добавляем рендер таблицы
        renderUsersTable(users);

        renderPagination();

    } catch (error) {
        console.error('Ошибка загрузки пользователей:', error);
        document.getElementById('usersTableBody').innerHTML = `
            <tr>
                <td colspan="8" class="error">❌ Ошибка загрузки: ${error.message}</td>
            </tr>
        `;
    }
}

function renderUsersTable(users) {
    const tbody = document.getElementById('usersTableBody');

    if (!users || users.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="8" class="empty">📭 Нет пользователей</td>
            </tr>
        `;
        return;
    }

    let html = '';
    users.forEach(user => {
        const isCurrentUser = user.username === currentUser;

        html += `
            <tr>
                <td>
                    <input type="checkbox" 
                           class="user-checkbox" 
                           value="${user.id}"
                           onchange="updateSelectedCount()"
                           ${isCurrentUser ? 'disabled' : ''}>
                </td>
                <td>${user.id}</td>
                <td>${user.username} ${isCurrentUser ? '(вы)' : ''}</td>
                <td>${user.email}</td>
                <td>
                    <span class="role-badge ${user.role}">
                        ${getRoleName(user.role)}
                    </span>
                </td>
                <td>
                    <span class="status-badge ${user.is_active ? 'active' : 'inactive'}">
                        ${user.is_active ? 'Активен' : 'Неактивен'}
                    </span>
                </td>
                <td>
                    <span class="twofa-badge ${user.otp_secret ? 'enabled' : 'disabled'}" 
                          title="${user.otp_secret ? '2FA включена' : '2FA отключена'}">
                        ${user.otp_secret ? '✅' : '❌'}
                    </span>
                </td>
                <td>
                    <div class="action-buttons">
                        <button onclick="editUser(${user.id})" 
                                class="action-btn edit"
                                ${isCurrentUser ? 'disabled' : ''}>
                            ✏️
                        </button>
                        <button onclick="resetPassword(${user.id}, '${user.username}')" 
                                class="action-btn reset-password"
                                ${isCurrentUser ? 'disabled' : ''}>
                            🔑
                        </button>
                        <button onclick="reset2FA(${user.id}, '${user.username}')" 
                                class="action-btn reset-2fa"
                                ${isCurrentUser || !user.otp_secret ? 'disabled' : ''}>
                            🔐
                        </button>
                        <button onclick="deleteUser(${user.id}, '${user.username}')" 
                                class="action-btn delete"
                                ${isCurrentUser ? 'disabled' : ''}>
                            🗑️
                        </button>
                    </div>
                </td>
            </tr>
        `;
    });

    tbody.innerHTML = html;
    updateSelectedCount();
}

function getRoleName(role) {
    const roles = {
        'admin': 'Администратор',
        'doctor': 'Врач',
        'user': 'Пользователь'
    };
    return roles[role] || role;
}

// ==================== Пагинация ====================

function renderPagination() {
    const totalPages = Math.ceil(totalUsers / pageSize);
    const pagination = document.getElementById('pagination');

    if (totalPages <= 1) {
        pagination.innerHTML = '';
        return;
    }

    let html = '';

    html += `<button class="page-btn" onclick="changePage(${currentPage - 1})" 
                    ${currentPage === 0 ? 'disabled' : ''}>←</button>`;

    for (let i = 0; i < totalPages; i++) {
        if (i === 0 || i === totalPages - 1 || (i >= currentPage - 2 && i <= currentPage + 2)) {
            html += `<button class="page-btn ${i === currentPage ? 'active' : ''}" 
                            onclick="changePage(${i})">${i + 1}</button>`;
        } else if (i === currentPage - 3 || i === currentPage + 3) {
            html += `<span class="page-dots">...</span>`;
        }
    }

    html += `<button class="page-btn" onclick="changePage(${currentPage + 1})" 
                    ${currentPage >= totalPages - 1 ? 'disabled' : ''}>→</button>`;

    pagination.innerHTML = html;
}

function changePage(page) {
    if (page < 0 || page >= Math.ceil(totalUsers / pageSize)) return;
    currentPage = page;
    loadUsers();
}

// ==================== Фильтры и поиск ====================

function applyFilters() {
    currentFilters = {
        search: document.getElementById('searchInput').value,
        role: document.getElementById('roleFilter').value,
        active_only: document.getElementById('statusFilter').value === 'active'
    };
    loadUsers(true);
}

function clearFilters() {
    document.getElementById('searchInput').value = '';
    document.getElementById('roleFilter').value = '';
    document.getElementById('statusFilter').value = '';
    currentFilters = { search: '', role: '', active_only: false };
    loadUsers(true);
}

let searchTimeout;
function debounceSearch() {
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(() => {
        applyFilters();
    }, 500);
}

// ==================== Выбор пользователей ====================

function toggleAllCheckboxes() {
    const selectAll = document.getElementById('selectAllCheckbox').checked;
    const checkboxes = document.querySelectorAll('.user-checkbox:not(:disabled)');

    checkboxes.forEach(cb => {
        cb.checked = selectAll;
        const userId = parseInt(cb.value);
        if (selectAll) selectedUsers.add(userId);
        else selectedUsers.delete(userId);
    });

    updateSelectedCount();
}

function updateSelectedCount() {
    const checkboxes = document.querySelectorAll('.user-checkbox:checked');
    selectedUsers.clear();

    checkboxes.forEach(cb => {
        selectedUsers.add(parseInt(cb.value));
    });

    document.getElementById('selectedCount').textContent = `Выбрано: ${selectedUsers.size}`;

    const totalCheckboxes = document.querySelectorAll('.user-checkbox:not(:disabled)').length;
    const checkedCheckboxes = checkboxes.length;
    const selectAllCheckbox = document.getElementById('selectAllCheckbox');

    if (selectAllCheckbox) {
        selectAllCheckbox.checked = checkedCheckboxes === totalCheckboxes && totalCheckboxes > 0;
        selectAllCheckbox.indeterminate = checkedCheckboxes > 0 && checkedCheckboxes < totalCheckboxes;
    }

    const bulkControls = document.querySelector('.bulk-controls');
    if (selectedUsers.size > 0) {
        bulkControls.classList.add('has-selection');
    } else {
        bulkControls.classList.remove('has-selection');
    }
}

// ==================== Выделение ====================

function updateBulkControls() {
    const bulkActions = document.getElementById('bulkActions');
    if (!bulkActions) return;

    bulkActions.style.display = selectedUsers.size > 0 ? 'flex' : 'none';

    const selectedCount = document.getElementById('selectedCount');
    if (selectedCount) {
        selectedCount.textContent = `Выбрано: ${selectedUsers.size}`;
    }

    const selectAll = document.getElementById('selectAllCheckbox');
    if (selectAll) {
        const checkboxes = document.querySelectorAll('.user-checkbox:not(:disabled)');
        const checked = document.querySelectorAll('.user-checkbox:checked').length;
        selectAll.checked = checked === checkboxes.length && checkboxes.length > 0;
        selectAll.indeterminate = checked > 0 && checked < checkboxes.length;
    }
}

function toggleUserSelection(id, checkbox) {
    if (checkbox.checked) {
        selectedUsers.add(id);
    } else {
        selectedUsers.delete(id);
    }
    updateBulkControls();
}

function toggleAllSelection(masterCheckbox) {
    const checkboxes = document.querySelectorAll('.user-checkbox:not(:disabled)');
    checkboxes.forEach(cb => {
        cb.checked = masterCheckbox.checked;
        toggleUserSelection(parseInt(cb.value), cb);
    });
}

function clearSelection() {
    selectedUsers.clear();
    document.querySelectorAll('.user-checkbox').forEach(cb => cb.checked = false);
    document.getElementById('selectAllCheckbox').checked = false;
    updateBulkControls();
    console.log('[DEBUG] Выделение очищено');
}

// ==================== Массовые действия ====================

async function executeBulkAction() {
    const action = document.getElementById('bulkActionSelect').value;

    if (!action) {
        showNotification('Выберите действие', 'warning');
        return;
    }

    if (selectedUsers.size === 0) {
        showNotification('Выберите пользователей', 'warning');
        return;
    }

    let confirmMessage = '';
    let role = null;

    if (action === 'activate') {
        confirmMessage = `Активировать ${selectedUsers.size} пользователей?`;
    } else if (action === 'deactivate') {
        confirmMessage = `Деактивировать ${selectedUsers.size} пользователей?`;
    } else if (action === 'change_role') {
        role = document.getElementById('bulkRoleSelect').value;
        if (!role) {
            showNotification('Выберите новую роль', 'warning');
            return;
        }
        confirmMessage = `Изменить роль ${selectedUsers.size} пользователей на "${getRoleName(role)}"?`;
    } else if (action === 'delete') {
        confirmMessage = `⚠️ УДАЛИТЬ ${selectedUsers.size} пользователей? Это действие необратимо!`;
    } else {
        return;
    }

    showConfirm(confirmMessage, async () => {
        try {
            const response = await fetch(`${API_BASE}/admin/users/bulk`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    action: action,
                    user_ids: Array.from(selectedUsers),  
                    ...(role ? { role } : {})
                }),
                credentials: 'include'
            });

            if (!response.ok) {
                if (response.status === 401 || response.status === 403) {
                    window.location.href = '/';
                    return;
                }
                const err = await response.json().catch(() => ({}));
                throw new Error(err.detail || `HTTP ${response.status}`);
            }

            const result = await response.json();

            showNotification(
                `${result.message || 'Действие выполнено'} — изменено ${result.affected || selectedUsers.size} пользователей`,
                'success'
            );

            // Очищаем выделение и обновляем данные
            clearSelection();
            await loadUsers();
            await loadUserStats();

        } catch (error) {
            console.error('[ERROR] Bulk action failed:', error);
            showNotification(`Ошибка массового действия: ${error.message}`, 'error');
        }
    });
}

// ==================== CRUD операции ====================

function showCreateUserModal() {
    document.getElementById('modalTitle').textContent = '➕ Создание пользователя';
    document.getElementById('userId').value = '';
    document.getElementById('modalUsername').value = '';
    document.getElementById('modalEmail').value = '';
    document.getElementById('modalPassword').value = '';
    document.getElementById('modalPassword').required = true;
    document.getElementById('modalRole').value = 'user';
    document.getElementById('modalIsActive').checked = true;
    document.getElementById('reset2faGroup').style.display = 'none';
    document.getElementById('modalSubmitBtn').textContent = 'Создать';
    document.getElementById('userModal').style.display = 'block';
}

async function editUser(userId) {
    try {
        const response = await fetch(`${API_BASE}/admin/users/${userId}`, {
            credentials: 'include'
        });

        if (!response.ok) {
            if (response.status === 401 || response.status === 403) {
                window.location.href = '/';
                return;
            }
            throw new Error('Ошибка загрузки данных пользователя');
        }

        const user = await response.json();

        document.getElementById('modalTitle').textContent = '✏️ Редактирование пользователя';
        document.getElementById('userId').value = user.id;
        document.getElementById('modalUsername').value = user.username;
        document.getElementById('modalUsername').disabled = true;
        document.getElementById('modalEmail').value = user.email;
        document.getElementById('modalPassword').value = '';
        document.getElementById('modalPassword').required = false;
        document.getElementById('modalRole').value = user.role;
        document.getElementById('modalIsActive').checked = user.is_active;

        const reset2faGroup = document.getElementById('reset2faGroup');
        if (user.otp_secret) {
            reset2faGroup.style.display = 'block';
            document.getElementById('modalReset2fa').checked = false;
        } else {
            reset2faGroup.style.display = 'none';
        }

        document.getElementById('modalSubmitBtn').textContent = 'Сохранить';
        document.getElementById('userModal').style.display = 'block';

    } catch (error) {
        showNotification(`Ошибка: ${error.message}`, 'error');
    }
}

function closeUserModal() {
    document.getElementById('userModal').style.display = 'none';
    document.getElementById('modalUsername').disabled = false;
}

async function handleUserSubmit(event) {
    event.preventDefault();

    const userId = document.getElementById('userId').value;
    const isEdit = !!userId;

    const formData = {
        username: document.getElementById('modalUsername').value.trim(),
        email: document.getElementById('modalEmail').value.trim(),
        role: document.getElementById('modalRole').value,
        is_active: document.getElementById('modalIsActive').checked
    };

    if (!formData.username) {
        showNotification('Логин не может быть пустым', 'error');
        return;
    }

    if (formData.username.length < 3 || formData.username.length > 50) {
        showNotification('Логин должен быть от 3 до 50 символов', 'error');
        return;
    }

    if (!/^[a-zA-Z0-9_]+$/.test(formData.username)) {
        showNotification('Логин может содержать только буквы, цифры и _', 'error');
        return;
    }

    if (!formData.email) {
        showNotification('Email не может быть пустым', 'error');
        return;
    }

    const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailPattern.test(formData.email)) {
        showNotification('Неверный формат email', 'error');
        return;
    }

    if (!isEdit) {
        const password = document.getElementById('modalPassword').value;
        if (!password) {
            showNotification('Введите пароль', 'error');
            return;
        }
        if (password.length < 8) {
            showNotification('Пароль должен быть не менее 8 символов', 'error');
            return;
        }
        formData.password = password;
    } else {
        const password = document.getElementById('modalPassword').value;
        if (password) {
            if (password.length < 8) {
                showNotification('Пароль должен быть не менее 8 символов', 'error');
                return;
            }
            formData.reset_password = true;
            formData.new_password = password;
        }

        if (document.getElementById('modalReset2fa')?.checked) {
            formData.reset_2fa = true;
        }
    }

    try {
        const url = isEdit ? `${API_BASE}/admin/users/${userId}` : `${API_BASE}/admin/users/`;
        const method = isEdit ? 'PUT' : 'POST';

        const response = await fetch(url, {
            method: method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(formData),
            credentials: 'include'
        });

        if (!response.ok) {
            if (response.status === 401 || response.status === 403) {
                window.location.href = '/';
                return;
            }
            const errorData = await response.json();
            throw new Error(errorData.detail || `HTTP ${response.status}`);
        }

        showNotification(isEdit ? 'Пользователь обновлен' : 'Пользователь создан', 'success');
        closeUserModal();
        await loadUsers();
        await loadUserStats();

    } catch (error) {
        console.error('Детальная ошибка:', error);
        showNotification(`Ошибка: ${error.message}`, 'error');
    }
}

function resetPassword(userId, username) {
    showConfirm(
        `Сбросить пароль пользователя ${username}?`,
        async () => {
            const newPassword = prompt('Введите новый пароль (минимум 8 символов):');

            if (!newPassword || newPassword.length < 8) {
                showNotification('Пароль должен быть не менее 8 символов', 'error');
                return;
            }

            try {
                const response = await fetch(`${API_BASE}/admin/users/${userId}/reset-password`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ new_password: newPassword }),
                    credentials: 'include'
                });

                if (!response.ok) {
                    if (response.status === 401 || response.status === 403) {
                        window.location.href = '/';
                        return;
                    }
                    const error = await response.json();
                    throw new Error(error.detail || 'Ошибка сброса пароля');
                }

                showNotification(`Пароль пользователя ${username} сброшен`, 'success');

            } catch (error) {
                showNotification(`Ошибка: ${error.message}`, 'error');
            }
        }
    );
}

function reset2FA(userId, username) {
    showConfirm(
        `Сбросить двухфакторную аутентификацию для ${username}?`,
        async () => {
            try {
                const response = await fetch(`${API_BASE}/admin/users/${userId}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ reset_2fa: true }),
                    credentials: 'include'
                });

                if (!response.ok) {
                    if (response.status === 401 || response.status === 403) {
                        window.location.href = '/';
                        return;
                    }
                    const error = await response.json();
                    throw new Error(error.detail || 'Ошибка сброса 2FA');
                }

                showNotification(`2FA для ${username} сброшена`, 'success');
                await loadUsers();

            } catch (error) {
                showNotification(`Ошибка: ${error.message}`, 'error');
            }
        }
    );
}

function deleteUser(userId, username) {
    showConfirm(
        `⚠️ УДАЛИТЬ пользователя ${username}?\nЭто действие необратимо!`,
        async () => {
            try {
                const response = await fetch(`${API_BASE}/admin/users/${userId}?confirm=true`, {
                    method: 'DELETE',
                    credentials: 'include'
                });

                if (!response.ok) {
                    if (response.status === 401 || response.status === 403) {
                        window.location.href = '/';
                        return;
                    }
                    const error = await response.json();
                    throw new Error(error.detail || 'Ошибка удаления');
                }

                showNotification(`Пользователь ${username} удален`, 'success');
                await loadUsers();
                await loadUserStats();

            } catch (error) {
                showNotification(`Ошибка: ${error.message}`, 'error');
            }
        }
    );
}

// ==================== Модальное окно подтверждения ====================

function showConfirm(message, callback) {
    document.getElementById('confirmMessage').textContent = message;
    document.getElementById('confirmModal').style.display = 'block';
    actionCallback = callback;
}

function closeConfirmModal() {
    document.getElementById('confirmModal').style.display = 'none';
    actionCallback = null;
}

function confirmAction() {
    if (actionCallback) actionCallback();
    closeConfirmModal();
}

// ==================== Уведомления ====================

function showNotification(message, type = 'info') {
    let container = document.getElementById('notificationContainer');
    if (!container) {
        container = document.createElement('div');
        container.id = 'notificationContainer';
        container.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            z-index: 9999;
        `;
        document.body.appendChild(container);
    }

    const notification = document.createElement('div');
    notification.style.cssText = `
        background: ${type === 'error' ? '#ff4444' : type === 'success' ? '#00C851' : '#33b5e5'};
        color: white;
        padding: 15px 20px;
        margin-bottom: 10px;
        border-radius: 5px;
        box-shadow: 0 3px 6px rgba(0,0,0,0.16);
        animation: slideIn 0.3s ease;
        max-width: 300px;
    `;
    notification.textContent = message;

    container.appendChild(notification);

    setTimeout(() => {
        notification.style.animation = 'slideOut 0.3s ease';
        setTimeout(() => {
            if (container.contains(notification)) {
                container.removeChild(notification);
            }
        }, 300);
    }, 5000);
}

// ==================== Выход ====================

async function logout() {
    if (!confirm('Вы уверены, что хотите выйти?')) return;

    try {
        const response = await fetch(`${API_BASE}/auth/logout`, {
            method: 'POST',
            credentials: 'include'
        });

        if (response.ok) {
            window.location.href = '/';
        } else {
            showNotification('Ошибка выхода', 'error');
        }
    } catch (e) {
        showNotification('Ошибка выхода: ' + e.message, 'error');
    }
}

// Анимации (оставляем)
const style = document.createElement('style');
style.textContent = `
    @keyframes slideIn {
        from { transform: translateX(100%); opacity: 0; }
        to { transform: translateX(0); opacity: 1; }
    }
    @keyframes slideOut {
        from { transform: translateX(0); opacity: 1; }
        to { transform: translateX(100%); opacity: 0; }
    }
`;
document.head.appendChild(style);