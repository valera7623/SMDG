// Единая инициализация темы (data-theme на <html>, localStorage, prefers-color-scheme).

export const THEME_STORAGE_KEY = 'smdg-theme';

/** Подсветка кнопок «Светлая» / «Тёмная» в соответствии с текущей темой. */
export function updateThemeToggleUI(doc = document) {
    const root = doc.documentElement;
    const isDark = root.getAttribute('data-theme') === 'dark';
    doc.querySelectorAll('.theme-switch [data-smdg-theme]').forEach((btn) => {
        const mode = btn.getAttribute('data-smdg-theme');
        const active =
            (mode === 'dark' && isDark) || (mode === 'light' && !isDark);
        btn.classList.toggle('is-active', active);
        btn.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
}

/**
 * Вешает обработчики на все `.theme-switch [data-smdg-theme]` под root.
 */
export function bindThemeToggles(root = document) {
    root.querySelectorAll('.theme-switch [data-smdg-theme]').forEach((btn) => {
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            const mode = btn.getAttribute('data-smdg-theme');
            if (mode === 'light' || mode === 'dark') {
                setSmdgTheme(mode);
            }
        });
    });
    updateThemeToggleUI(root instanceof Document ? root : document);
}

export function initTheme() {
    const root = document.documentElement;
    try {
        const stored = localStorage.getItem(THEME_STORAGE_KEY);
        if (stored === 'dark' || stored === 'light') {
            if (stored === 'dark') {
                root.setAttribute('data-theme', 'dark');
            } else {
                root.removeAttribute('data-theme');
            }
            updateThemeToggleUI();
            return;
        }
    } catch {
        /* private mode */
    }
    if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
        root.setAttribute('data-theme', 'dark');
    } else {
        root.removeAttribute('data-theme');
    }
    updateThemeToggleUI();
}

/**
 * @param {'dark'|'light'|'system'} mode
 */
export function setSmdgTheme(mode) {
    const root = document.documentElement;
    if (mode === 'dark') {
        root.setAttribute('data-theme', 'dark');
    } else if (mode === 'light') {
        root.removeAttribute('data-theme');
    } else {
        try {
            localStorage.removeItem(THEME_STORAGE_KEY);
        } catch {
            /* ignore */
        }
        initTheme();
        return;
    }
    try {
        localStorage.setItem(THEME_STORAGE_KEY, mode);
    } catch {
        /* ignore */
    }
    updateThemeToggleUI();
}
