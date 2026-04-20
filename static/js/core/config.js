// static/js/core/config.js

import { t } from '../utils/i18n.js';

export const API_BASE = '/api';

export const PAGE_SIZE = 10;

export const NOTIFICATION_DURATION = 5000; // ms

export const FILE_AUTO_REMOVE_DELAY = 30000; // ms — убирать блок загрузки

export const FILE_REFRESH_INTERVAL = 30000; // ms — автообновление списка файлов

export const ROLE_NAMES = {
    admin:  'Administrator',
    doctor: 'Doctor',
    user:   'User',
};

/**
 * Return the localized display name for a role. Falls back to the
 * English name defined in `ROLE_NAMES` if the translation runtime is
 * not ready or the key is missing.
 *
 * @param {string} role "admin" | "doctor" | "user" | string
 * @returns {string}
 */
export function roleName(role) {
    const fallback = ROLE_NAMES[role] || role;
    return t(`admin.role_${role}`, fallback);
}