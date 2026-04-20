// static/js/core/api.js
// Единая точка для всех HTTP-запросов к бэкенду.

import { API_BASE } from './config.js';

// ── Приватная обёртка ─────────────────────────────────────────────────────────

/**
 * Базовый fetch с credentials и централизованной обработкой 401/403.
 * Бросает Error с полем `status` при неудаче.
 */
async function request(path, options = {}) {
    const response = await fetch(`${API_BASE}${path}`, {
        credentials: 'include',
        ...options,
    });

    if (response.status === 401 || response.status === 403) {
        // Редирект выполняет вызывающий модуль — мы бросаем специальный флаг
        const err = new Error('Unauthorized');
        err.status = response.status;
        throw err;
    }

    return response;
}

async function requestJSON(path, options = {}) {
    const response = await request(path, options);

    if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        const err  = new Error(data.detail || `HTTP ${response.status}`);
        err.status = response.status;
        throw err;
    }

    return response.json();
}

// ── Auth ──────────────────────────────────────────────────────────────────────

export const auth = {
    async login(username, password, otpCode = '') {
        const body = new URLSearchParams({ username, password });
        if (otpCode) body.append('otp_code', otpCode);

        return request('/auth/login', {
            method:  'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body,
        });
    },

    async register(username, email, password) {
        return requestJSON('/auth/register', {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify({ username, email, password }),
        });
    },

    async logout() {
        return request('/auth/logout', { method: 'POST' });
    },

    async whoami() {
        return request('/whoami');
    },

    async setup2FA() {
        return requestJSON('/auth/setup-2fa', {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
        });
    },

    async verify2FA(code) {
        return requestJSON('/auth/verify-2fa-setup', {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify({ code }),
        });
    },

    async changePassword(oldPassword, newPassword) {
        return requestJSON('/auth/change-password', {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify({ old_password: oldPassword, new_password: newPassword }),
        });
    },
};

// ── Files (пользовательские) ──────────────────────────────────────────────────

export const files = {
    async list() {
        return requestJSON('/list');
    },

    async upload(file) {
        const formData = new FormData();
        formData.append('file', file);

        const data = await requestJSON('/upload', {
            method: 'POST',
            body: formData,
        });

        console.log('API upload response:', data);
        return data;
    },

    async download(filename) {
        const response = await request(
            `/download?filename=${encodeURIComponent(filename)}`,
        );

        if (!response.ok) {
            const error = new Error(`HTTP ${response.status}`);
            error.status = response.status;
            throw error;
        }

        return response;
    },

    async deleteUserFile(filename) {
        const body = new URLSearchParams({ filename, confirm: 'true' });
        return requestJSON('/delete-user-file', {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body,
        });
    },
};

// ── Admin — файлы ─────────────────────────────────────────────────────────────

export const adminFiles = {
    async list() {
        return requestJSON('/list');
    },

    async download(filename) {
        return files.download(filename);
    },

    async delete(filename) {
        const body = new URLSearchParams({ filename, confirm: 'true', reason: 'manual_delete' });
        return requestJSON('/delete', {
            method:  'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body,
        });
    },

    async cleanupStats() {
        return requestJSON('/cleanup/stats');
    },

    async purge() {
        return requestJSON('/cleanup/force', {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
        });
    },
};

// ── System ────────────────────────────────────────────────────────────────────

export const system = {
    async health() {
        return requestJSON('/health');
    },

    async stats() {
        return requestJSON('/stats');
    },
};

// ── Admin — пользователи ──────────────────────────────────────────────────────

export const adminUsers = {
    async stats() {
        return requestJSON('/admin/users/stats/overview');
    },

    async list({ skip = 0, limit = 10, search = '', role = '', active_only = false } = {}) {
        let url = `/admin/users/?skip=${skip}&limit=${limit}`;
        if (search)       url += `&search=${encodeURIComponent(search)}`;
        if (role)         url += `&role=${role}`;
        if (active_only)  url += `&active_only=true`;

        const response = await request(url);
        if (!response.ok) {
            const data = await response.json().catch(() => ({}));
            const err  = new Error(data.detail || `HTTP ${response.status}`);
            err.status = response.status;
            throw err;
        }

        const users      = await response.json();
        const totalCount = response.headers.get('X-Total-Count') ?? users.length;
        return { users, total: parseInt(totalCount) };
    },

    async get(userId) {
        return requestJSON(`/admin/users/${userId}`);
    },

    async create(data) {
        return requestJSON('/admin/users/', {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify(data),
        });
    },

    async update(userId, data) {
        return requestJSON(`/admin/users/${userId}`, {
            method:  'PUT',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify(data),
        });
    },

    async delete(userId) {
        return requestJSON(`/admin/users/${userId}?confirm=true`, { method: 'DELETE' });
    },

    async resetPassword(userId, newPassword) {
        return requestJSON(`/admin/users/${userId}/reset-password`, {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify({ new_password: newPassword }),
        });
    },

    async bulk(action, userIds, role = null) {
        return requestJSON('/admin/users/bulk', {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify({
                action,
                user_ids: userIds,
                ...(role ? { role } : {}),
            }),
        });
    },
};