/**
 * Плавные переходы между HTML-страницами (multi-page).
 * — появление контента при загрузке;
 * — затухание перед переходом по same-origin ссылкам.
 */

const LEAVE_MS = 280;

function prefersReducedMotion() {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

function pageShell() {
    return document.querySelector('.container') || document.body;
}

/** Плавный переход программно (редирект после входа и т.п.). */
export function navigateWithTransition(url) {
    if (!url || prefersReducedMotion()) {
        window.location.assign(url);
        return;
    }
    document.body.classList.add('smdg-page-leaving');
    window.setTimeout(() => window.location.assign(url), LEAVE_MS);
}

function shouldHandleLink(link, event) {
    if (event.defaultPrevented) return false;
    if (event.button !== 0) return false;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return false;

    const href = link.getAttribute('href');
    if (!href || href.startsWith('#') || href.startsWith('javascript:')) return false;
    if (link.target && link.target !== '_self') return false;
    if (link.hasAttribute('download')) return false;
    if (link.dataset.smdgNoTransition !== undefined) return false;

    let url;
    try {
        url = new URL(link.href, window.location.href);
    } catch {
        return false;
    }

    if (url.origin !== window.location.origin) return false;
    if (url.pathname === window.location.pathname
        && url.search === window.location.search
        && url.hash) {
        return false;
    }

    return true;
}

function onDocumentClick(event) {
    if (prefersReducedMotion()) return;

    const link = event.target.closest('a[href]');
    if (!link || !shouldHandleLink(link, event)) return;

    event.preventDefault();
    document.body.classList.add('smdg-page-leaving');

    const destination = link.href;
    window.setTimeout(() => {
        window.location.assign(destination);
    }, LEAVE_MS);
}

let _pageTransitionsReady = false;

export function initPageTransitions() {
    if (_pageTransitionsReady) return;
    _pageTransitionsReady = true;
    const shell = pageShell();
    if (shell && !prefersReducedMotion()) {
        shell.classList.add('smdg-page-shell');
    }

    document.addEventListener('click', onDocumentClick, true);
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initPageTransitions, { once: true });
} else {
    initPageTransitions();
}
