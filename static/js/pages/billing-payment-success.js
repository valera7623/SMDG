import { payments as paymentsAPI } from '../core/api.js';
import { mountShell } from '../layout.js';
import { loadingHtml } from '../ui.js';
import { navigate } from '../router.js';
import { showNotification } from '../utils/notifications.js';
import { t } from '../utils/i18n.js';

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = String(text ?? '');
    return div.innerHTML;
}

export async function renderBillingPaymentSuccess(root, params = {}) {
    mountShell(root, t('billing.payment_title', 'Оплата'), loadingHtml());

    const paymentId = params.payment_id
        || new URLSearchParams(location.search).get('payment_id')
        || sessionStorage.getItem('yookassa_last_payment_id')
        || '';

    if (paymentId) {
        try {
            const statusData = await paymentsAPI.yookassaStatus(paymentId);
            if (statusData.status === 'canceled') {
                navigate(`/payment/cancel?payment_id=${encodeURIComponent(paymentId)}`);
                return;
            }
            if (statusData.status !== 'succeeded') {
                mountShell(root, t('billing.payment_title', 'Оплата'), `<div class="card"><div class="card-body">
                  <h3>${t('billing.payment_pending', 'Оплата в процессе')}</h3>
                  <p class="text-muted">${escapeHtml(statusData.status)}</p>
                </div></div>`);
                return;
            }
        } catch (err) {
            showNotification(err.message, 'error');
        }
    }

    mountShell(
        root,
        t('billing.payment_success', 'Оплата успешна'),
        `<div class="card"><div class="card-body">
          <h3>✅ ${t('billing.activated', 'Подписка активирована')}</h3>
          <p>${t('billing.limits_updated', 'Лимиты обновлены.')}</p>
          <div style="display:flex;gap:.75rem;margin-top:1rem">
            <button type="button" class="btn" id="to-files">${t('files.list', 'Файлы')}</button>
            <button type="button" class="btn btn-outline" id="to-sub">${t('billing.subscription_title', 'Подписка')}</button>
          </div>
        </div></div>`,
        (el) => {
            el.querySelector('#to-files')?.addEventListener('click', () => navigate('/files'));
            el.querySelector('#to-sub')?.addEventListener('click', () => navigate('/subscription'));
        },
    );
}
