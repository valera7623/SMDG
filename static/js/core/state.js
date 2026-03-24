// static/js/core/state.js

import { PAGE_SIZE } from './config.js';

// ── Пользователь ──────────────────────────────────────────────────────────────
export let currentUser = null;
export function setCurrentUser(user) { currentUser = user; }

// ── Выбор пользователей (admin-users) ────────────────────────────────────────
export const selectedUsers = new Set();

export function clearSelectedUsers() {
    selectedUsers.clear();
}

// ── Пагинация (admin-users) ───────────────────────────────────────────────────
export let currentPage = 0;
export let pageSize    = PAGE_SIZE;
export let totalUsers  = 0;

export function setCurrentPage(page) { currentPage = page; }
export function setTotalUsers(total) { totalUsers  = total; }

// ── Фильтры (admin-users) ─────────────────────────────────────────────────────
export let currentFilters = {
    search:      '',
    role:        '',
    active_only: false,
};

export function setFilters(filters) {
    currentFilters = { ...currentFilters, ...filters };
}

export function resetFilters() {
    currentFilters = { search: '', role: '', active_only: false };
}

// ── Колбэк подтверждения (modal confirm) ──────────────────────────────────────
export let actionCallback = null;
export function setActionCallback(fn) { actionCallback = fn; }
export function clearActionCallback()  { actionCallback = null; }