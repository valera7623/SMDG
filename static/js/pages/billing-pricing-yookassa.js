import { payments as paymentsAPI } from '../core/api.js';
import { mountShell } from '../layout.js';
import { navigate } from '../router.js';
import { showNotification } from '../utils/notifications.js';
import { t } from '../utils/i18n.js';

const PLANS = [
    { key: 'freemium', title: 'Freemium', priceLabel: '0 ₽', uploads: '10 загрузок / месяц', action: null },
    { key: 'premium_monthly', title: 'Premium (Monthly)', priceLabel: '19.90 ₽', uploads: '500 загрузок / месяц', action: 'premium_monthly' },
    { key: 'premium_yearly', title: 'Premium (Yearly)', priceLabel: '199.00 ₽ / год', uploads: '500 загрузок / месяц', action: 'premium_yearly' },
    { key: 'enterprise', title: 'Enterprise', priceLabel: '99.90 ₽', uploads: '5000 загрузок / месяц', action: 'enterprise' },
];

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = String(text ?? '');
    return div.innerHTML;
}

export async function renderBillingPricingYookassa(root) {
    mountShell(
        root,
        t('billing.yookassa_title', 'Тарифы (ЮKassa)'),
        `<div class="page-header">
          <h1>${t('billing.yookassa_title', 'Тарифы — ЮKassa')}</h1>
          <p><a href="#/pricing">← Stripe</a></p>
        </div>
        <div class="grid-4">
          ${PLANS.map((p) => `
            <div class="card"><div class="card-body">
              <h3>${escapeHtml(p.title)}</h3>
              <div class="stat-value" style="margin:.75rem 0">${escapeHtml(p.priceLabel)}</div>
              <p><b>${escapeHtml(p.uploads)}</b></p>
              ${p.action
                ? `<button class="btn" data-buy="${escapeHtml(p.action)}">${t('billing.pay_yookassa', 'Оплатить через ЮKassa')}</button>`
                : `<button class="btn btn-outline" disabled>${t('billing.included', 'Включено')}</button>`}
            </div></div>`).join('')}
        </div>`,
        (el) => {
            el.querySelectorAll('[data-buy]').forEach((btn) => {
                btn.addEventListener('click', async () => {
                    btn.disabled = true;
                    try {
                        const data = await paymentsAPI.yookassaCreate(btn.dataset.buy);
                        sessionStorage.setItem('yookassa_last_payment_id', data.payment_id);
                        window.location.href = data.confirmation_url;
                    } catch (err) {
                        showNotification(err.message, 'error');
                        btn.disabled = false;
                    }
                });
            });
        },
    );
}
