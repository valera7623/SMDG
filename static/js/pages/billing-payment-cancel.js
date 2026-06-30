import { mountShell } from '../layout.js';
import { navigate } from '../router.js';
import { t } from '../utils/i18n.js';

export async function renderBillingPaymentCancel(root) {
    mountShell(
        root,
        t('billing.payment_cancelled', 'Оплата отменена'),
        `<div class="card"><div class="card-body">
          <h3>${t('billing.payment_cancelled', 'Оплата отменена')}</h3>
          <p class="text-muted">${t('billing.try_again', 'Вы можете попробовать снова.')}</p>
          <button type="button" class="btn" id="to-pricing">${t('billing.pricing_title', 'Тарифы')}</button>
        </div></div>`,
        (el) => el.querySelector('#to-pricing')?.addEventListener('click', () => navigate('/pricing')),
    );
}
