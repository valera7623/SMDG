// static/js/utils/dom.js

/**
 * Экранирует HTML-спецсимволы.
 * Используется везде вместо inline-replace цепочек.
 */
export function escapeHtml(unsafe) {
    if (typeof unsafe !== 'string') return '';
    return unsafe
        .replace(/&/g,  '&amp;')
        .replace(/</g,  '&lt;')
        .replace(/>/g,  '&gt;')
        .replace(/"/g,  '&quot;')
        .replace(/'/g,  '&#039;')
        .replace(/\//g, '&#x2F;');
}

/**
 * Создаёт DOM-элемент с опциональными атрибутами и дочерними элементами.
 *
 * @param {string} tag
 * @param {Object} [attrs] — className, textContent, style, data-*, ...
 * @param {...(Node|string)} children
 * @returns {HTMLElement}
 */
export function createElement(tag, attrs = {}, ...children) {
    const el = document.createElement(tag);

    for (const [key, value] of Object.entries(attrs)) {
        if (key === 'className') {
            el.className = value;
        } else if (key === 'textContent') {
            el.textContent = value;
        } else if (key === 'style' && typeof value === 'object') {
            Object.assign(el.style, value);
        } else if (key.startsWith('on') && typeof value === 'function') {
            el.addEventListener(key.slice(2).toLowerCase(), value);
        } else {
            el.setAttribute(key, value);
        }
    }

    for (const child of children) {
        if (child instanceof Node) {
            el.appendChild(child);
        } else if (child != null) {
            el.appendChild(document.createTextNode(String(child)));
        }
    }

    return el;
}

/**
 * Безопасно обновляет innerHTML элемента строкой.
 * Используй только с заранее проверенными строками!
 */
export function setHTML(el, html) {
    if (el) el.innerHTML = html;
}

/**
 * Находит элемент и обновляет его textContent.
 */
export function setText(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text ?? '—';
}

/**
 * Показывает / скрывает элемент (display flex / none).
 */
export function setVisible(el, visible, display = 'block') {
    if (!el) return;
    el.style.display = visible ? display : 'none';
}