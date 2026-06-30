import { appState, subscribe, toggleSidebar, toggleTheme } from "./app-state.js";
import { navigate } from "./router.js";
import { escapeHtml } from "./utils.js";
import { t, currentLang } from "./utils/i18n.js";

function docsHref() {
  return currentLang() === "ru" ? "/help/" : "/help/en/";
}

function billingNavItem(current) {
  if (!window.__BILLING_UI_ENABLED__) return '';
  return navLink(
    { path: '/pricing', labelKey: 'nav.billing', fallback: 'Тарифы', icon: '💳' },
    current,
  );
}

function userNavItems(current) {
  return [
    ...userNav.map((n) => navLink(n, current)),
    billingNavItem(current),
  ].join('');
}

const userNav = [
  { path: "/files", labelKey: "files.list", fallback: "Файлы", icon: "📋" },
];

const adminNav = [
  { path: "/admin/files", labelKey: "admin.files_section", fallback: "Файлы", icon: "📁" },
  { path: "/admin/users", labelKey: "admin.users", fallback: "Пользователи", icon: "👥" },
  { path: "/admin/dlq", labelKey: "admin_dlq.title", fallback: "DLQ", icon: "📬" },
];

function externalNavItems() {
  return [
    { href: docsHref(), labelKey: "nav.docs", fallback: "Документация", icon: "📖" },
    { href: "/health", labelKey: "nav.health", fallback: "Health", icon: "🩺" },
    { href: "/docs", labelKey: "nav.api_docs", fallback: "API", icon: "📚" },
  ];
}

function navLink(item, current) {
  const active = current === item.path ? "active" : "";
  const label = t(item.labelKey, item.fallback);
  return `<a href="#${item.path}" class="nav-link ${active}"><span>${item.icon}</span>${label}</a>`;
}

function externalLink(item) {
  const label = t(item.labelKey, item.fallback);
  return `<a href="${item.href}" class="nav-link" target="_blank" rel="noopener"><span>${item.icon}</span>${label}</a>`;
}

export function renderShell(contentHtml, title = "") {
  const hash = location.hash.replace(/^#/, "") || "/files";
  const current = hash.split("?")[0];
  const adminSection = appState.isAdmin
    ? `<div class="nav-section">${t("nav.admin", "Админ")}</div>${adminNav.map((n) => navLink(n, current)).join("")}`
    : "";

  return `
    <div class="layout ${appState.sidebarOpen ? "sidebar-open" : ""}">
      <div class="sidebar-backdrop" data-action="close-sidebar"></div>
      <aside class="sidebar">
        <div class="sidebar-brand">🔐 SMDG</div>
        <nav class="sidebar-nav">
          ${userNavItems(current)}
          ${adminSection}
          <div class="nav-section">${t("nav.external", "Сервис")}</div>
          ${externalNavItems().map((n) => externalLink(n)).join("")}
        </nav>
      </aside>
      <div class="main">
        <header class="header">
          <button type="button" class="btn-icon menu-btn" data-action="toggle-sidebar">☰</button>
          <p class="header-title" role="heading" aria-level="2">${escapeHtml(title)}</p>
          <div class="header-actions">
            <a href="${docsHref()}" class="btn btn-outline btn-sm" target="_blank" rel="noopener">${t("nav.docs", "Документация")}</a>
            <div id="smdgLangAndMenu" class="header-lang"></div>
            <span class="key-badge" title="${t("auth.username", "Пользователь")}">👤 ${escapeHtml(appState.username || "—")}${appState.isAdmin ? ' <span class="badge">Admin</span>' : ""}</span>
            <button type="button" class="btn-icon" data-action="toggle-theme" title="${t("theme.toolbar_label", "Тема")}">${appState.theme === "dark" ? "☀️" : "🌙"}</button>
            <button type="button" class="btn btn-outline btn-sm" data-action="logout">${t("auth.logout", "Выход")}</button>
          </div>
        </header>
        <main class="content">${contentHtml}</main>
      </div>
    </div>`;
}

export function mountShell(root, title, contentHtml, bindExtra) {
  root.innerHTML = renderShell(contentHtml, title);
  window.I18N?.addLanguageSelector?.();
  root.querySelector('[data-action="toggle-sidebar"]')?.addEventListener("click", () => toggleSidebar());
  root.querySelector('[data-action="close-sidebar"]')?.addEventListener("click", () => toggleSidebar(false));
  root.querySelector('[data-action="toggle-theme"]')?.addEventListener("click", () => toggleTheme());
  bindExtra?.(root);
}

export function initLayoutSubscription(renderFn) {
  subscribe(() => {
    const hash = location.hash.replace(/^#/, "");
    if (hash && !PUBLIC_AUTH_PATHS.has(hash.split("?")[0])) renderFn();
  });
}

const PUBLIC_AUTH_PATHS = new Set(["/login", "/register"]);

export function bindLogout(handler) {
  document.querySelector('[data-action="logout"]')?.addEventListener("click", handler);
}
