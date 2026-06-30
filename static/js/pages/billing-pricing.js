import { payments as paymentsAPI } from '../core/api.js';
import { mountShell } from '../layout.js';
import { loadingHtml } from '../ui.js';
import { navigate } from '../router.js';
import { showNotification } from '../utils/notifications.js';
import { t } from '../utils/i18n.js';

function formatUsdCents(cents) {
    if (cents == null) return '—';
    return `$${(cents / 100).toFixed(2)}`;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = String(text ?? '');
    return div.innerHTML;
}

async function startCheckout(priceId) {
    const origin = window.location.origin;
    const data = await paymentsAPI.createCheckout({
        price_id: priceId,
        success_url: `${origin}/payment/success?session_id={CHECKOUT_SESSION_ID}`,
        cancel_url: `${origin}/payment/cancel`,
    });
    if (!data?.url) throw new Error('Stripe checkout URL missing');
    sessionStorage.setItem('stripe_last_session_id', data.session_id);
    window.location.href = data.url;
}

export async function renderBillingPricing(root) {
    let config = { billing_enabled: false, stripe_enabled: false };
    try {
        config = await paymentsAPI.config();
    } catch {
        /* ignore */
    }

    if (!config.billing_enabled) {
        mountShell(
            root,
            t('billing.pricing_title', 'Тарифы'),
            `<div class="card"><div class="card-body">
              <p>${t('billing.test_mode', 'Оплата отключена — тестовый режим без лимитов загрузок.')}</p>
              <button type="button" class="btn btn-outline" id="to-files">${t('files.list', 'Файлы')}</button>
            </div></div>`,
            (el) => el.querySelector('#to-files')?.addEventListener('click', () => navigate('/files')),
        );
        return;
    }

    mountShell(root, t('billing.pricing_title', 'Тарифы'), loadingHtml());

    let prices = [];
    try {
        const catalog = await paymentsAPI.prices();
        prices = catalog?.prices || [];
    } catch {
        prices = [];
    }

    const freemiumCard = `
      <div class="card"><div class="card-body">
        <h3>Freemium</h3>
        <p class="text-muted">${t('billing.free_start', 'Бесплатный старт')}</p>
        <div class="stat-value" style="margin:.75rem 0">$0</div>
        <p><b>10 ${t('billing.uploads_month', 'загрузок / месяц')}</b></p>
        <button class="btn btn-outline" disabled>${t('billing.included', 'Включено')}</button>
      </div></div>`;

    const paidCards = prices.length
        ? prices.map((p) => `
        <div class="card"><div class="card-body">
          <h3>${escapeHtml(p.name)}</h3>
          <p class="text-muted">${escapeHtml(p.interval ? `/${p.interval}` : 'one-time')}</p>
          <div class="stat-value" style="margin:.75rem 0">${formatUsdCents(p.amount)}</div>
          <button class="btn" data-stripe-price="${escapeHtml(p.id)}">${t('billing.buy_stripe', 'Купить через Stripe')}</button>
        </div></div>`).join('')
        : `<div class="card"><div class="card-body">
            <p class="text-muted">${t('billing.stripe_not_configured', 'Настройте STRIPE_PRICE_ID_* в .env')}</p>
          </div></div>`;

    mountShell(
        root,
        t('billing.pricing_title', 'Тарифы'),
        `<div class="page-header"><h1>${t('billing.pricing_title', 'Тарифы')}</h1></div>
         <div class="grid-4">${freemiumCard}${paidCards}</div>
         <p class="text-muted" style="margin-top:1.5rem">
           <a href="#/pricing-yookassa">${t('billing.yookassa_alt', 'Оплата через ЮKassa (РФ)')}</a>
         </p>`,
        (el) => {
            el.querySelectorAll('[data-stripe-price]').forEach((btn) => {
                btn.addEventListener('click', async () => {
                    btn.disabled = true;
                    try {
                        await startCheckout(btn.dataset.stripePrice);
                    } catch (err) {
                        showNotification(err.message, 'error');
                        btn.disabled = false;
                    }
                });
            });
        },
    );
}
