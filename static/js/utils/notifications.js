// static/js/utils/notifications.js

import { NOTIFICATION_DURATION } from '../core/config.js';

// Вставляем анимации один раз
const _style = document.createElement('style');
_style.textContent = `
    @keyframes slideIn {
        from { transform: translateX(110%); opacity: 0; }
        to   { transform: translateX(0);    opacity: 1; }
    }
    @keyframes slideOut {
        from { transform: translateX(0);    opacity: 1; }
        to   { transform: translateX(110%); opacity: 0; }
    }
    #notificationContainer .notification {
        color: white;
        padding: 14px 20px;
        margin-bottom: 10px;
        border-radius: 6px;
        box-shadow: 0 3px 8px rgba(0,0,0,0.2);
        animation: slideIn 0.3s ease;
        max-width: 320px;
        word-break: break-word;
        cursor: pointer;
        font-size: 14px;
        line-height: 1.4;
    }
`;
document.head.appendChild(_style);

const COLORS = {
    error:   '#e74c3c',
    success: '#27ae60',
    warning: '#f39c12',
    info:    '#2980b9',
};

function getContainer() {
    let el = document.getElementById('notificationContainer');
    if (!el) {
        el = document.createElement('div');
        el.id = 'notificationContainer';
        el.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            z-index: 9999;
        `;
        document.body.appendChild(el);
    }
    return el;
}

/**
 * Показывает всплывающее уведомление.
 *
 * @param {string} message
 * @param {'info'|'success'|'error'|'warning'} [type='info']
 * @param {number} [duration] — мс, по умолчанию из config
 */
export function showNotification(message, type = 'info', duration = NOTIFICATION_DURATION) {
    const container    = getContainer();
    const notification = document.createElement('div');

    notification.className = 'notification';
    notification.style.background = COLORS[type] ?? COLORS.info;
    notification.textContent = message;

    // Клик — закрыть немедленно
    notification.addEventListener('click', () => dismiss(container, notification));

    container.appendChild(notification);

    setTimeout(() => dismiss(container, notification), duration);
}

function dismiss(container, el) {
    el.style.animation = 'slideOut 0.3s ease forwards';
    el.addEventListener('animationend', () => {
        if (container.contains(el)) container.removeChild(el);
    }, { once: true });
}
