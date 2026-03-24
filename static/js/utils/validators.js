// static/js/utils/validators.js

/**
 * Проверяет формат email.
 * @param {string} email
 * @returns {boolean}
 */
export function isValidEmail(email) {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
}

/**
 * Проверяет username: 3–50 символов, только буквы/цифры/_.
 * @param {string} username
 * @returns {{ valid: boolean, error?: string }}
 */
export function validateUsername(username) {
    if (!username || username.length < 3 || username.length > 50) {
        return { valid: false, error: 'Логин от 3 до 50 символов' };
    }
    if (!/^[a-zA-Z0-9_]+$/.test(username)) {
        return { valid: false, error: 'Логин: только буквы, цифры и _' };
    }
    return { valid: true };
}

/**
 * Проверяет пароль: минимум 8 символов.
 * @param {string} password
 * @returns {{ valid: boolean, error?: string }}
 */
export function validatePassword(password) {
    if (!password || password.length < 8) {
        return { valid: false, error: 'Пароль минимум 8 символов' };
    }
    return { valid: true };
}

/**
 * Рассчитывает «силу» пароля (0–4).
 * @param {string} password
 * @returns {number}
 */
export function passwordStrength(password) {
    let score = 0;
    if (password.length >= 8)  score++;
    if (password.length >= 12) score++;
    if (/[A-Z]/.test(password) && /[a-z]/.test(password)) score++;
    if (/[0-9]/.test(password))  score++;
    if (/[^a-zA-Z0-9]/.test(password)) score++;
    return Math.min(score, 4);
}
