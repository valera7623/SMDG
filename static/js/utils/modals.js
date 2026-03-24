// static/js/utils/modals.js

import { setActionCallback, clearActionCallback, actionCallback } from '../core/state.js';

/**
 * Показывает встроенное модальное окно подтверждения (#confirmModal).
 *
 * @param {string}   message
 * @param {Function} callback — вызывается при нажатии «Подтвердить»
 */
export function showConfirm(message, callback) {
    const msgEl = document.getElementById('confirmMessage');
    const modal = document.getElementById('confirmModal');
    if (msgEl) msgEl.textContent = message;
    if (modal) modal.style.display = 'block';
    setActionCallback(callback);
}

export function closeConfirmModal() {
    const modal = document.getElementById('confirmModal');
    if (modal) modal.style.display = 'none';
    clearActionCallback();
}

export function confirmAction() {
    if (actionCallback) actionCallback();
    closeConfirmModal();
}

/**
 * Открывает/закрывает произвольное модальное окно по id.
 */
export function showModal(id) {
    const el = document.getElementById(id);
    if (el) el.style.display = 'block';
}

export function closeModal(id) {
    const el = document.getElementById(id);
    if (el) el.style.display = 'none';
}

// Закрытие по клику вне модалки
document.addEventListener('click', (e) => {
    if (e.target.classList.contains('modal')) {
        e.target.style.display = 'none';
        clearActionCallback();
    }
});
