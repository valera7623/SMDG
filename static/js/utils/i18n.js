// static/js/utils/i18n.js
//
// Thin wrapper around the global `window.I18N` runtime so that ES modules
// can call `t('some.key', 'English fallback')` without directly poking at
// the global. When `window.I18N` has not yet loaded (or is unavailable)
// the helper returns the provided English fallback so the UI stays
// readable.
//
// Parameter interpolation uses the same `{{param}}` syntax as
// `window.I18N.t`.

/**
 * Translate a key with optional params. Falls back to the English string
 * when no translation runtime is present or the key is missing.
 *
 * @param {string} key      Dotted translation key, e.g. "files.upload".
 * @param {string} fallback English text to use when the key is missing.
 * @param {Object} [params] Optional interpolation parameters.
 * @returns {string}
 */
export function t(key, fallback, params) {
    let resolvedFallback = fallback;
    let resolvedParams = params;

    if (
        resolvedParams === undefined &&
        resolvedFallback !== undefined &&
        resolvedFallback !== null &&
        typeof resolvedFallback === "object" &&
        !Array.isArray(resolvedFallback)
    ) {
        resolvedParams = resolvedFallback;
        resolvedFallback = undefined;
    }

    const runtime = typeof window !== "undefined" ? window.I18N : null;
    if (runtime && typeof runtime.t === "function") {
        const value = runtime.t(key, resolvedParams);
        if (value && value !== key) return value;
    }
    if (typeof resolvedFallback !== "string") return key;
    if (!resolvedParams) return resolvedFallback;
    let out = resolvedFallback;
    for (const name of Object.keys(resolvedParams)) {
        const safe = String(resolvedParams[name]);
        out = out.replace(
            new RegExp(`{{\\s*${name.replace(/[.*+?^${}()|[\\]\\\\]/g, "\\$&")}\\s*}}`, "g"),
            safe,
        );
    }
    return out;
}

/**
 * Return the current UI language code (`en`, `ru`, `de`, `fr`) or `en`
 * if the runtime has not initialised yet.
 */
export function currentLang() {
    const runtime = typeof window !== 'undefined' ? window.I18N : null;
    return (runtime && runtime.currentLang) || 'en';
}

/**
 * Locale code suitable for `toLocaleString()` calls. Returns BCP-47-ish
 * strings that JavaScript `Intl` understands.
 */
export function currentLocale() {
    const lang = currentLang();
    return { en: 'en-US', ru: 'ru-RU', de: 'de-DE', fr: 'fr-FR' }[lang] || 'en-US';
}
