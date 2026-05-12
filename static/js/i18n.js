/**
 * SMDG internationalisation (i18n) runtime for the Vanilla JS frontend.
 *
 * Usage:
 *   1. Mark any translatable element with `data-i18n="key"` (textContent).
 *   2. For form fields use `data-i18n-placeholder="key"` to translate the
 *      placeholder or `data-i18n-value="key"` for submit button values.
 *   3. Mark the document title with `data-i18n-title="key"` on any node.
 *   4. Use `data-i18n-aria-label="key"` for accessible names on inputs/buttons.
 *   5. Import this file last; it auto-initialises on DOMContentLoaded.
 *   6. To translate dynamically injected content call
 *      `window.I18N.updatePageTranslations()` after injection, or
 *      listen for the `i18n:updated` event.
 *
 * Locale files live in `/static/locales/<lang>.js` and register their
 * dictionaries on `window.SMDG_I18N.translations[<lang>]`. No `eval`
 * or dynamic `import()` is used — each locale is a regular script.
 */
(function () {
    "use strict";

    /**
     * База URL для `locales/<lang>.js` (не хардкодить `/static/` при другом STATIC_URL или префиксе прокси).
     */
    function localesBaseUrl() {
        try {
            const cfg = window.SMDG_CONFIG && window.SMDG_CONFIG.static_url;
            if (cfg) {
                return String(cfg).replace(/\/?$/, "/") + "locales/";
            }
        } catch (_e) {
            /* ignore */
        }
        const marker = document.querySelector('script[src*="i18n.js"]');
        if (marker && marker.src) {
            try {
                const u = new URL(marker.src, document.baseURI);
                const path = u.pathname.replace(/\/js\/i18n[^/]*$/i, "/locales/");
                if (path !== u.pathname) {
                    return u.origin + (path.endsWith("/") ? path : `${path}/`);
                }
            } catch (_e) {
                /* ignore */
            }
        }
        return "/static/locales/";
    }

    function localeQueryString() {
        try {
            const v = window.SMDG_CONFIG && window.SMDG_CONFIG.asset_version;
            if (v) return `?v=${encodeURIComponent(String(v))}`;
        } catch (_e) {
            /* ignore */
        }
        const marker = document.querySelector('script[src*="i18n.js"]');
        if (marker && marker.src && marker.src.includes("?")) {
            return `?${marker.src.split("?")[1]}`;
        }
        return "";
    }

    const STORAGE_KEY = "smdg_language";
    const RTL_LANGS = new Set(["ar", "he", "fa", "ur"]);

    const I18N = {
        currentLang: "en",
        availableLangs: ["en", "ru", "de", "fr"],
        langNames: {
            en: "English",
            ru: "Русский",
            de: "Deutsch",
            fr: "Français",
        },
        fallbackLang: "en",
        _initialised: false,
        /** @type {Promise<void> | null} */
        _initPromise: null,
        _pendingLoads: new Map(),

        get translations() {
            if (!window.SMDG_I18N) {
                window.SMDG_I18N = { translations: {} };
            }
            if (!window.SMDG_I18N.translations) {
                window.SMDG_I18N.translations = {};
            }
            return window.SMDG_I18N.translations;
        },

        /**
         * Detect the best initial language based on localStorage, the
         * browser preferences and the available translations.
         */
        detectInitialLang() {
            const saved = this._readStorage(STORAGE_KEY);
            if (saved && this.availableLangs.includes(saved)) return saved;

            const browserLangs = [
                ...(navigator.languages || []),
                navigator.language || "",
            ];
            for (const tag of browserLangs) {
                const code = (tag || "").toLowerCase().split("-")[0];
                if (this.availableLangs.includes(code)) return code;
            }
            return this.fallbackLang;
        },

        /**
         * Ensure the translations for `lang` are loaded, injecting the
         * locale script tag if needed. Returns a promise resolved when
         * `window.SMDG_I18N.translations[lang]` is available.
         */
        loadTranslations(lang) {
            if (this.translations[lang]) return Promise.resolve(true);
            if (this._pendingLoads.has(lang)) return this._pendingLoads.get(lang);

            const promise = new Promise((resolve) => {
                const existing = document.querySelector(
                    `script[data-i18n-lang="${lang}"]`
                );
                if (existing) {
                    if (this.translations[lang]) {
                        resolve(true);
                        return;
                    }
                    let settled = false;
                    const done = (ok) => {
                        if (settled) return;
                        settled = true;
                        resolve(ok);
                    };
                    const onLoad = () => done(Boolean(this.translations[lang]));
                    existing.addEventListener("load", onLoad, { once: true });
                    existing.addEventListener("error", () => done(false), { once: true });
                    queueMicrotask(() => {
                        if (this.translations[lang]) done(true);
                    });
                    window.setTimeout(() => {
                        if (!settled) {
                            console.warn(`[i18n] Locale script wait timeout: ${lang}`);
                            done(Boolean(this.translations[lang]));
                        }
                    }, 12000);
                    return;
                }
                const script = document.createElement("script");
                script.src = `${localesBaseUrl()}${lang}.js${localeQueryString()}`;
                script.async = true;
                script.defer = true;
                script.dataset.i18nLang = lang;
                script.addEventListener(
                    "load",
                    () => resolve(Boolean(this.translations[lang])),
                    { once: true }
                );
                script.addEventListener(
                    "error",
                    () => {
                        console.error(`[i18n] Failed to load locale: ${lang} (${script.src})`);
                        resolve(false);
                    },
                    { once: true }
                );
                document.head.appendChild(script);
            });

            this._pendingLoads.set(lang, promise);
            promise.finally(() => {
                this._pendingLoads.delete(lang);
            });
            return promise;
        },

        /**
         * Change the active language and re-render the DOM.
         */
        async setLanguage(lang) {
            if (!this.availableLangs.includes(lang)) {
                lang = this.fallbackLang;
            }

            const okPrimary = await this.loadTranslations(lang);
            if (!okPrimary && lang !== this.fallbackLang) {
                console.warn(`[i18n] Locale «${lang}» failed to load; falling back to ${this.fallbackLang}`);
                lang = this.fallbackLang;
                await this.loadTranslations(lang);
            }
            if (lang !== this.fallbackLang) {
                await this.loadTranslations(this.fallbackLang);
            }

            this.currentLang = lang;
            this._writeStorage(STORAGE_KEY, lang);
            document.documentElement.lang = lang;
            document.documentElement.dir = RTL_LANGS.has(lang) ? "rtl" : "ltr";

            this.updatePageTranslations();
            return true;
        },

        /**
         * Translate a key with optional `{{param}}` substitution. Falls
         * back to the English dictionary and finally to the key itself
         * when a translation is missing.
         */
        t(key, params) {
            const dict = this.translations[this.currentLang] || {};
            const fallback = this.translations[this.fallbackLang] || {};
            let text = dict[key];
            if (text == null) text = fallback[key];
            if (text == null) return key;

            if (params && typeof params === "object") {
                for (const name of Object.keys(params)) {
                    const safe = String(params[name]);
                    text = text.replace(
                        new RegExp(`{{\\s*${escapeRegExp(name)}\\s*}}`, "g"),
                        safe
                    );
                }
            }
            return text;
        },

        /**
         * Translate every element in the DOM annotated with
         * `data-i18n`, `data-i18n-placeholder`, `data-i18n-value`,
         * `data-i18n-title` or `data-i18n-aria-label`. Safe to call multiple times.
         */
        updatePageTranslations(root) {
            const scope = root || document;

            scope.querySelectorAll("[data-i18n]").forEach((el) => {
                const key = el.getAttribute("data-i18n");
                if (key) el.textContent = this.t(key);
            });

            scope.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
                const key = el.getAttribute("data-i18n-placeholder");
                if (key) el.setAttribute("placeholder", this.t(key));
            });

            scope.querySelectorAll("[data-i18n-value]").forEach((el) => {
                const key = el.getAttribute("data-i18n-value");
                if (key) el.value = this.t(key);
            });

            scope.querySelectorAll("[data-i18n-aria-label]").forEach((el) => {
                const key = el.getAttribute("data-i18n-aria-label");
                if (key) el.setAttribute("aria-label", this.t(key));
            });

            scope.querySelectorAll("[data-i18n-title]").forEach((el) => {
                const key = el.getAttribute("data-i18n-title");
                if (!key) return;
                if (el.tagName === "TITLE" || el === document) {
                    document.title = this.t(key);
                } else {
                    el.setAttribute("title", this.t(key));
                }
            });

            const titleEl = document.querySelector("title[data-i18n]");
            if (titleEl) document.title = this.t(titleEl.getAttribute("data-i18n"));

            window.dispatchEvent(
                new CustomEvent("i18n:updated", {
                    detail: { lang: this.currentLang },
                })
            );
        },

        /**
         * Inject a language dropdown into the page.  The dropdown
         * attaches itself to the first matching container or to the
         * document body as a fixed element.
         */
        addLanguageSelector(containerSelector) {
            if (document.getElementById("language-selector")) return;

            const selector = document.createElement("div");
            selector.id = "language-selector";
            selector.className = "language-selector";
            selector.innerHTML = `
                <button class="lang-btn" id="lang-btn" type="button"
                        aria-haspopup="listbox" aria-expanded="false"
                        title="${this.escapeHtml(this.t("language.selector"))}">
                    <span aria-hidden="true">🌐</span>
                    <span class="lang-btn-label">${this.escapeHtml(this.langNames[this.currentLang])}</span>
                </button>
                <div class="lang-dropdown" id="lang-dropdown" role="listbox">
                    ${this.availableLangs
                        .map(
                            (lang) => `
                        <a href="#" data-lang="${lang}" role="option"
                           class="lang-option ${lang === this.currentLang ? "active" : ""}">
                            ${this.escapeHtml(this.langNames[lang])}
                        </a>`
                        )
                        .join("")}
                </div>
            `;

            const container = containerSelector
                ? document.querySelector(containerSelector)
                : document.querySelector(
                    "#smdgLangAndMenu, #ohif-header .buttons, #viewer-header, #ohif-header, .navbar, header .user-info, header"
                );
            if (container) {
                container.appendChild(selector);
            } else {
                selector.classList.add("floating");
                document.body.appendChild(selector);
            }

            const btn = selector.querySelector("#lang-btn");
            const dropdown = selector.querySelector("#lang-dropdown");

            btn.addEventListener("click", (event) => {
                event.stopPropagation();
                const open = dropdown.classList.toggle("show");
                btn.setAttribute("aria-expanded", String(open));
            });

            selector.querySelectorAll(".lang-option").forEach((option) => {
                option.addEventListener("click", async (event) => {
                    event.preventDefault();
                    const lang = option.getAttribute("data-lang");
                    await this.setLanguage(lang);

                    selector.querySelectorAll(".lang-option").forEach((opt) => {
                        opt.classList.toggle(
                            "active",
                            opt.getAttribute("data-lang") === lang
                        );
                    });
                    btn.querySelector(".lang-btn-label").textContent =
                        this.langNames[lang];
                    dropdown.classList.remove("show");
                    btn.setAttribute("aria-expanded", "false");
                });
            });

            document.addEventListener("click", (event) => {
                if (!selector.contains(event.target)) {
                    dropdown.classList.remove("show");
                    btn.setAttribute("aria-expanded", "false");
                }
            });

            document.addEventListener("keydown", (event) => {
                if (event.key === "Escape") {
                    dropdown.classList.remove("show");
                    btn.setAttribute("aria-expanded", "false");
                }
            });
        },

        /**
         * Initialise the runtime: detect language, load translations,
         * render translations and insert the language selector.
         */
        async init(options) {
            if (this._initPromise) return this._initPromise;

            this._initPromise = (async () => {
                const opts = options || {};
                const lang = opts.lang || this.detectInitialLang();
                await this.setLanguage(lang);
                if (opts.renderSelector !== false) {
                    this.addLanguageSelector(opts.selectorContainer);
                }
                this._initialised = true;
            })();

            return this._initPromise;
        },

        // --- helpers -------------------------------------------------

        escapeHtml(value) {
            return String(value).replace(/[&<>"']/g, (c) => ({
                "&": "&amp;",
                "<": "&lt;",
                ">": "&gt;",
                '"': "&quot;",
                "'": "&#39;",
            })[c]);
        },

        _readStorage(key) {
            try {
                return window.localStorage.getItem(key);
            } catch (_err) {
                return null;
            }
        },

        _writeStorage(key, value) {
            try {
                window.localStorage.setItem(key, value);
            } catch (_err) {
                /* storage disabled — fail silently */
            }
        },
    };

    function escapeRegExp(value) {
        return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    }

    window.I18N = I18N;

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", () => {
            void I18N.init();
        });
    } else {
        void I18N.init();
    }
})();
