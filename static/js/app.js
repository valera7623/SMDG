import { initAppState, setUser, clearUser } from "./app-state.js";
import { initRouter, registerRoute, renderRoute, navigate } from "./router.js";
import { auth as authAPI } from "./core/api.js";
import { setCurrentUser } from "./core/state.js";
import { renderLogin, doLogout } from "./pages/auth.js";
import { renderFiles } from "./pages/files.js";
import { renderAdminFiles } from "./pages/admin-files-page.js";
import { renderAdminUsers, renderAdminDlq, stopDlqTimer } from "./pages/admin-pages.js";
import { appState } from "./app-state.js";

async function checkFeatureFlags() {
  try {
    const resp = await fetch("/health");
    if (resp.ok) {
      const data = await resp.json();
      window.__DICOM_VIEWER_ENABLED__ = !!data.features?.dicom_viewer;
    }
  } catch {
    window.__DICOM_VIEWER_ENABLED__ = false;
  }
}

async function refreshSession() {
  try {
    const data = await authAPI.whoami();
    setCurrentUser(data.sub);
    setUser(data.sub, data.role);
    return data;
  } catch {
    setCurrentUser(null);
    clearUser();
    return null;
  }
}

async function handleLogout() {
  await doLogout();
  clearUser();
  navigate("/login");
}

const app = document.getElementById("app");

async function boot() {
  if (window.I18N?.init) await window.I18N.init();

  initAppState();
  initRouter();

  registerRoute("/login", (root, params) => renderLogin(root, params));
  registerRoute("/register", (root) => renderLogin(root, { tab: "register" }));
  registerRoute("/files", (root) => renderFiles(root));
  registerRoute("/admin/files", (root) => renderAdminFiles(root));
  registerRoute("/admin/users", (root) => renderAdminUsers(root));
  registerRoute("/admin/dlq", (root) => renderAdminDlq(root));

  await checkFeatureFlags();
  await refreshSession();

  if (!location.hash || location.hash === "#") {
    location.hash = appState.isAuthenticated ? "#/files" : "#/login";
  }

  document.addEventListener("click", (e) => {
    if (e.target.closest('[data-action="logout"]')) {
      e.preventDefault();
      void handleLogout();
    }
  });

  window.addEventListener("hashchange", () => {
    const path = location.hash.replace(/^#/, "").split("?")[0];
    if (path !== "/admin/dlq") stopDlqTimer();
  });

  window.addEventListener("i18n:updated", () => {
    void renderRoute();
  });

  window.__smdgOnAuthSuccess = async () => {
    const data = await refreshSession();
    if (data) navigate("/files");
  };

  await renderRoute();
}

boot();
