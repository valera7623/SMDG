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

function planLabel(plan) {
    const map = { freemium: 'Freemium', premium: 'Premium', enterprise: 'Enterprise' };
    return map[plan] || plan;
}

export async function renderBillingSubscription(root) {
    mountShell(root, t('billing.subscription_title', 'Подписка'), loadingHtml());

    try {
        const sub = await paymentsAPI.subscription();
        const periodEnd = sub.current_period_end
            ? `<p><b>${t('billing.valid_until', 'Действует до')}:</b> ${escapeHtml(sub.current_period_end)}</p>`
            : '';
        const cancelBtn = sub.stripe_subscription_id && sub.is_active
            ? `<button type="button" class="btn btn-outline" id="cancel-sub">${t('billing.cancel', 'Отменить подписку')}</button>`
            : '';

        mountShell(
            root,
            t('billing.subscription_title', 'Подписка'),
            `<div class="page-header"><h1>${t('billing.subscription_title', 'Подписка')}</h1></div>
             <div class="card" style="max-width:520px"><div class="card-body">
               <p><b>${t('billing.plan', 'Тариф')}:</b> ${escapeHtml(planLabel(sub.plan_type))}</p>
               <p><b>${t('billing.status', 'Статус')}:</b> ${escapeHtml(sub.status)}</p>
               <p><b>${t('billing.uploads', 'Загрузки')}:</b> ${sub.uploads_used} / ${sub.uploads_limit}
                  (${t('billing.remaining', 'осталось')} ${sub.uploads_remaining})</p>
               ${periodEnd}
               <div style="display:flex;gap:.75rem;flex-wrap:wrap;margin-top:1.25rem">
                 <button type="button" class="btn" id="to-pricing">${t('billing.change_plan', 'Сменить тариф')}</button>
                 ${cancelBtn}
               </div>
             </div></div>`,
            (el) => {
                el.querySelector('#to-pricing')?.addEventListener('click', () => navigate('/pricing'));
                el.querySelector('#cancel-sub')?.addEventListener('click', async () => {
                    if (!confirm(t('billing.cancel_confirm', 'Отменить подписку?'))) return;
                    try {
                        await paymentsAPI.cancelSubscription();
                        showNotification(t('billing.cancelled', 'Подписка отменена'), 'success');
                        renderBillingSubscription(root);
                    } catch (err) {
                        showNotification(err.message, 'error');
                    }
                });
            },
        );
    } catch (err) {
        showNotification(err.message, 'error');
        mountShell(root, t('billing.subscription_title', 'Подписка'),
            `<p class="text-muted">${t('billing.load_error', 'Не удалось загрузить подписку.')}</p>`);
    }
}
