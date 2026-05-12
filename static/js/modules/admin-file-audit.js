// static/js/modules/admin-file-audit.js

import { adminFileAudit } from '../core/api.js';
import { createElement } from '../utils/dom.js';
import { formatBytes } from '../utils/formats.js';
import { currentLocale, t } from '../utils/i18n.js';

const PAGE_SIZE = 20;
let currentSkip = 0;
let currentTotal = 0;

const REDIRECT_HOME = () => { window.location.href = '/'; };

export function initFileAudit() {
    document.getElementById('fileAuditRefresh')?.addEventListener('click', () => {
        currentSkip = 0;
        loadFileAuditEvents();
    });
    document.getElementById('fileAuditReset')?.addEventListener('click', () => {
        ['fileAuditSearch', 'fileAuditAction', 'fileAuditSuccess', 'fileAuditStart', 'fileAuditEnd']
            .forEach(id => {
                const el = document.getElementById(id);
                if (el) el.value = '';
            });
        currentSkip = 0;
        loadFileAuditEvents();
    });
    loadFileAuditEvents();
}

export async function loadFileAuditEvents() {
    const container = document.getElementById('fileAuditList');
    if (!container) return;

    container.innerHTML = `<div class="loading">${t('admin_file_audit.loading', 'Loading file audit…')}</div>`;

    try {
        const data = await adminFileAudit.list({
            skip: currentSkip,
            limit: PAGE_SIZE,
            search: _value('fileAuditSearch'),
            action: _value('fileAuditAction'),
            success: _value('fileAuditSuccess'),
            start: _dateValue('fileAuditStart'),
            end: _dateValue('fileAuditEnd'),
        });
        currentTotal = data.total || 0;
        _renderAuditTable(container, data.items || []);
    } catch (error) {
        if (error.status === 401 || error.status === 403) { REDIRECT_HOME(); return; }
        container.innerHTML = '';
        container.appendChild(createElement('div', {
            className: 'error',
            textContent: t('admin_file_audit.error', 'Error: {{message}}', { message: error.message }),
        }));
    }
}

function _renderAuditTable(container, events) {
    container.innerHTML = '';
    if (events.length === 0) {
        container.appendChild(createElement('div', {
            className: 'empty',
            textContent: t('admin_file_audit.empty', 'No file audit events found'),
        }));
        _renderPagination(container);
        return;
    }

    const table = createElement('table', { className: 'data-table responsive-data-table' });
    const labels = {
        time: t('admin_file_audit.col_time', 'Time'),
        action: t('admin_file_audit.col_action', 'Action'),
        user: t('admin_file_audit.col_user', 'User'),
        file: t('admin_file_audit.col_file', 'File'),
        size: t('admin_file_audit.col_size', 'Size'),
        ip: t('admin_file_audit.col_ip', 'IP'),
        direction: t('admin_file_audit.col_direction', 'Direction'),
        status: t('admin_file_audit.col_status', 'Status'),
    };
    const thead = createElement('thead', {},
        createElement('tr', {},
            ...Object.values(labels).map(
                title => createElement('th', { textContent: title }),
            ),
        ),
    );
    const tbody = createElement('tbody');

    events.forEach(event => {
        const userLabel = [event.actor_username || t('admin_file_audit.unknown', 'unknown'), event.actor_role || '']
            .filter(Boolean)
            .join(' / ');
        const direction = `${event.source || '—'} -> ${event.destination || '—'}`;
        tbody.appendChild(createElement('tr', {},
            _td(labels.time, _formatDate(event.created_at)),
            _td(labels.action, _actionLabel(event.action)),
            _td(labels.user, userLabel),
            _td(labels.file, event.original_name || event.encrypted_name || '—'),
            _td(labels.size, event.size_bytes ? formatBytes(event.size_bytes) : '—'),
            _td(labels.ip, event.client_ip || '—'),
            _td(labels.direction, direction),
            _td(labels.status, event.success
                ? t('admin_file_audit.status_ok', 'OK')
                : t('admin_file_audit.status_failed_with_reason', 'Failed: {{reason}}', {
                    reason: event.failure_reason || t('admin_file_audit.unknown', 'unknown'),
                })),
        ));
    });

    table.appendChild(thead);
    table.appendChild(tbody);
    container.appendChild(createElement('div', { className: 'table-container' }, table));
    _renderPagination(container);
}

function _renderPagination(container) {
    const start = currentTotal === 0 ? 0 : currentSkip + 1;
    const end = Math.min(currentSkip + PAGE_SIZE, currentTotal);
    const prevDisabled = currentSkip <= 0;
    const nextDisabled = currentSkip + PAGE_SIZE >= currentTotal;

    const prev = createElement('button', {
        className: 'btn-secondary',
        textContent: t('admin_file_audit.previous', 'Previous'),
    });
    prev.addEventListener('click', () => {
        currentSkip = Math.max(0, currentSkip - PAGE_SIZE);
        loadFileAuditEvents();
    });

    const next = createElement('button', {
        className: 'btn-secondary',
        textContent: t('admin_file_audit.next', 'Next'),
    });
    next.addEventListener('click', () => {
        currentSkip += PAGE_SIZE;
        loadFileAuditEvents();
    });

    if (prevDisabled) prev.disabled = true;
    if (nextDisabled) next.disabled = true;

    container.appendChild(createElement('div', { className: 'pagination' },
        prev,
        createElement('span', { textContent: `${start}-${end} / ${currentTotal}` }),
        next,
    ));
}

function _td(label, text) {
    return createElement('td', { 'data-label': label, textContent: text ?? '—' });
}

function _actionLabel(action) {
    const keyByAction = {
        upload: 'admin_file_audit.action_upload',
        download_authenticated: 'admin_file_audit.action_download_user',
        download_token: 'admin_file_audit.action_download_link',
    };
    const key = keyByAction[action];
    return key ? t(key, action) : action;
}

function _value(id) {
    return document.getElementById(id)?.value?.trim() || '';
}

function _dateValue(id) {
    const value = _value(id);
    return value ? new Date(value).toISOString() : '';
}

function _formatDate(value) {
    if (!value) return '—';
    try {
        return new Intl.DateTimeFormat(currentLocale(), {
            dateStyle: 'short',
            timeStyle: 'medium',
        }).format(new Date(value));
    } catch (_error) {
        return value;
    }
}
