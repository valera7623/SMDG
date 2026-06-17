import { NOTIFICATION_DURATION } from '../core/config.js';
import { toast } from '../ui.js';

/**
 * Показывает уведомление в стиле ReportAgent (toast справа сверху).
 */
export function showNotification(message, type = 'info', _duration = NOTIFICATION_DURATION) {
    const mapped = type === 'warning' ? 'error' : type;
    toast(message, mapped);
}
