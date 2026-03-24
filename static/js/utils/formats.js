// static/js/utils/formats.js

/**
 * Форматирует размер в байтах → человекочитаемую строку.
 * Объединяет formatBytes (main.js) и formatFileSize (admin.js).
 *
 * @param {number|null|undefined} bytes
 * @param {number} [decimals=2]
 * @returns {string}
 */
export function formatBytes(bytes, decimals = 2) {
    if (bytes === null || bytes === undefined) return '—';
    if (bytes === 0) return '0 Bytes';

    const k     = 1024;
    const dm    = Math.max(0, decimals);
    const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
    const i     = Math.floor(Math.log(bytes) / Math.log(k));

    return `${parseFloat((bytes / Math.pow(k, i)).toFixed(dm))} ${sizes[i]}`;
}

/**
 * Форматирует ISO-дату → локальную строку (ru-RU).
 *
 * @param {string|null|undefined} iso
 * @returns {string}
 */
export function formatDate(iso) {
    if (!iso) return '—';
    return new Date(iso).toLocaleString('ru-RU');
}