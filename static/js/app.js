import { initAppState, setUser, clearUser } from "./app-state.js";
import { initRouter, registerRoute, renderRoute, navigate } from "./router.js";
import { auth as authAPI } from "./core/api.js";
import { setCurrentUser } from "./core/state.js";
import { renderLogin, doLogout } from "./pages/auth.js";
import { renderFiles } from "./pages/files.js";
import { renderAdminFiles } from "./pages/admin-files-page.js";
import { renderAdminUsers, renderAdminDlq, stopDlqTimer } from "./pages/admin-pages.js";
import { renderBillingPricing } from "./pages/billing-pricing.js";
import { renderBillingPricingYookassa } from "./pages/billing-pricing-yookassa.js";
import { renderBillingSubscription } from "./pages/billing-subscription.js";
import { renderBillingPaymentSuccess } from "./pages/billing-payment-success.js";
import { renderBillingPaymentCancel } from "./pages/billing-payment-cancel.js";
import { payments as paymentsAPI } from "./core/api.js";
import { appState } from "./app-state.js";

window.__BILLING_UI_ENABLED__ = false;

async function checkFeatureFlags() {
  try {
    const resp = await fetch("/health");
    if (resp.ok) {
      const data = await resp.json();
      window.__DICOM_VIEWER_ENABLED__ = !!data.features?.dicom_viewer;
      window.__BILLING_FEATURE__ = !!data.features?.billing;
    }
  } catch {
    window.__DICOM_VIEWER_ENABLED__ = false;
    window.__BILLING_FEATURE__ = false;
  }

  window.__BILLING_UI_ENABLED__ = !!window.__BILLING_FEATURE__;

  if (appState.isAuthenticated) {
    try {
      const cfg = await paymentsAPI.config();
      window.__BILLING_UI_ENABLED__ = !!(
        window.__BILLING_FEATURE__ || cfg.billing_enabled || cfg.stripe_enabled || cfg.yookassa_enabled
      );
    } catch {
      /* keep feature-flag default */
    }
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
  registerRoute("/pricing", (root) => renderBillingPricing(root));
  registerRoute("/pricing-yookassa", (root) => renderBillingPricingYookassa(root));
  registerRoute("/subscription", (root) => renderBillingSubscription(root));
  registerRoute("/payment/success", (root, params) => renderBillingPaymentSuccess(root, params));
  registerRoute("/payment/cancel", (root) => renderBillingPaymentCancel(root));
  registerRoute("/success", (root, params) => renderBillingPaymentSuccess(root, params));
  registerRoute("/cancel", (root) => renderBillingPaymentCancel(root));

  await refreshSession();
  await checkFeatureFlags();

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
    await checkFeatureFlags();
    if (data) navigate("/files");
  };

  await renderRoute();
}

boot();
