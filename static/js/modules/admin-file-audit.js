// static/js/modules/admin-file-audit.js

import { adminFileAudit } from '../core/api.js';
import { createElement } from '../utils/dom.js';
import { formatBytes } from '../utils/formats.js';

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

    container.innerHTML = '<div class="loading">Loading file audit…</div>';

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
        container.appendChild(createElement('div', { className: 'error', textContent: `Error: ${error.message}` }));
    }
}

function _renderAuditTable(container, events) {
    container.innerHTML = '';
    if (events.length === 0) {
        container.appendChild(createElement('div', { className: 'empty', textContent: 'No file audit events found' }));
        _renderPagination(container);
        return;
    }

    const table = createElement('table', { className: 'data-table responsive-data-table' });
    const thead = createElement('thead', {},
        createElement('tr', {},
            ...['Time', 'Action', 'User', 'File', 'Size', 'IP', 'Direction', 'Status'].map(
                title => createElement('th', { textContent: title }),
            ),
        ),
    );
    const tbody = createElement('tbody');

    events.forEach(event => {
        const userLabel = [event.actor_username || 'unknown', event.actor_role || '']
            .filter(Boolean)
            .join(' / ');
        const direction = `${event.source || '—'} -> ${event.destination || '—'}`;
        tbody.appendChild(createElement('tr', {},
            _td('Time', _formatDate(event.created_at)),
            _td('Action', event.action),
            _td('User', userLabel),
            _td('File', event.original_name || event.encrypted_name || '—'),
            _td('Size', event.size_bytes ? formatBytes(event.size_bytes) : '—'),
            _td('IP', event.client_ip || '—'),
            _td('Direction', direction),
            _td('Status', event.success ? 'OK' : `Failed: ${event.failure_reason || 'unknown'}`),
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
        textContent: 'Previous',
    });
    prev.addEventListener('click', () => {
        currentSkip = Math.max(0, currentSkip - PAGE_SIZE);
        loadFileAuditEvents();
    });

    const next = createElement('button', {
        className: 'btn-secondary',
        textContent: 'Next',
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
        return new Intl.DateTimeFormat(undefined, {
            dateStyle: 'short',
            timeStyle: 'medium',
        }).format(new Date(value));
    } catch (_error) {
        return value;
    }
}
