import { auth as authAPI } from "../core/api.js";
import { setCurrentUser } from "../core/state.js";
import {
  switchAuthTab,
  handleSetup2FA,
  logout as moduleLogout,
  updatePasswordStrength,
} from "../modules/auth.js";
import { navigate } from "../router.js";
import { toast } from "../ui.js";
import { t } from "../utils/i18n.js";

export async function renderLogin(root, params = {}) {
  if (params.registered === "1") {
    toast(t("auth.register_success", "Регистрация успешна. Войдите в систему."), "success");
  }

  root.innerHTML = `
    <div class="login-page">
      <div class="login-card">
        <h1>SMDG</h1>
        <p class="seo-lead">${t("app.subtitle", "Безопасная передача медицинских файлов")}</p>
        <div id="smdgLangAndMenu" style="margin-bottom:1rem"></div>
        <div class="tabs" style="display:flex;gap:.5rem;margin-bottom:1rem">
          <button type="button" class="btn btn-sm" id="tab-login" data-tab="login">${t("auth.tab_login", "Вход")}</button>
          <button type="button" class="btn btn-outline btn-sm" id="tab-register" data-tab="register">${t("auth.tab_register", "Регистрация")}</button>
        </div>
        <div id="panel-login">
          <p id="authSubtitle">${t("auth.subtitle_login", "Вход в систему")}</p>
          <form id="loginForm">
            <div class="form-group">
              <label for="loginUsername">${t("auth.username", "Имя пользователя")}</label>
              <input id="loginUsername" type="text" required autocomplete="username" />
            </div>
            <div class="form-group">
              <label for="loginPassword">${t("auth.password", "Пароль")}</label>
              <input id="loginPassword" type="password" required autocomplete="current-password" />
            </div>
            <div class="form-group" id="loginOtpGroup" hidden>
              <label for="loginOtpCode">${t("auth.2fa_code", "Код 2FA")}</label>
              <input id="loginOtpCode" type="text" maxlength="6" pattern="[0-9]{6}" inputmode="numeric" />
            </div>
            <button type="submit" class="btn" style="width:100%">${t("auth.login", "Войти")}</button>
            <p class="text-muted" style="margin-top:1rem;font-size:.85rem">
              <a href="#" id="forgot-password">${t("auth.forgot_password", "Забыли пароль?")}</a>
            </p>
          </form>
        </div>
        <div id="panel-register" hidden>
          <p>${t("auth.subtitle_register", "Регистрация нового пользователя")}</p>
          <form id="registerForm">
            <div class="form-group">
              <label for="registerUsername">${t("auth.username", "Имя пользователя")}</label>
              <input id="registerUsername" type="text" required minlength="3" maxlength="50" />
            </div>
            <div class="form-group">
              <label for="registerEmail">${t("auth.email", "Email")}</label>
              <input id="registerEmail" type="email" required />
            </div>
            <div class="form-group">
              <label for="registerPassword">${t("auth.password", "Пароль")}</label>
              <input id="registerPassword" type="password" required minlength="8" />
              <div class="password-strength"><div class="strength-bar"></div></div>
            </div>
            <div class="form-group">
              <label for="registerConfirmPassword">${t("auth.password_confirm", "Подтвердите пароль")}</label>
              <input id="registerConfirmPassword" type="password" required />
            </div>
            <div class="form-group">
              <label class="checkbox-inline">
                <input id="registerAgreeTerms" type="checkbox" required />
                ${t("auth.agree_terms", "Я согласен с условиями использования")}
              </label>
            </div>
            <button type="submit" class="btn" style="width:100%">${t("auth.register", "Зарегистрироваться")}</button>
          </form>
        </div>
      </div>
    </div>`;

  const panelLogin = root.querySelector("#panel-login");
  const panelRegister = root.querySelector("#panel-register");
  const tabLogin = root.querySelector("#tab-login");
  const tabRegister = root.querySelector("#tab-register");

  function showTab(tab) {
    const isLogin = tab === "login";
    panelLogin.hidden = !isLogin;
    panelRegister.hidden = isLogin;
    tabLogin.className = isLogin ? "btn btn-sm" : "btn btn-outline btn-sm";
    tabRegister.className = isLogin ? "btn btn-outline btn-sm" : "btn btn-sm";
    switchAuthTab(tab);
  }

  tabLogin.onclick = () => showTab("login");
  tabRegister.onclick = () => showTab("register");

  root.querySelector("#loginForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const { handleLogin } = await import("../modules/auth.js");
    await handleLogin(e);
  });

  root.querySelector("#registerForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const { handleRegister } = await import("../modules/auth.js");
    await handleRegister(e);
  });

  root.querySelector("#forgot-password").addEventListener("click", (e) => {
    e.preventDefault();
    toast(t("auth.forgot_hint", "Свяжитесь с администратором"), "info");
  });

  const passInput = root.querySelector("#registerPassword");
  passInput?.addEventListener("input", () => updatePasswordStrength(passInput));

  if (params.tab === "register") showTab("register");

  window.I18N?.addLanguageSelector?.();
}

export { handleSetup2FA, moduleLogout as doLogout };

export async function refreshSession() {
  try {
    const data = await authAPI.whoami();
    setCurrentUser(data.sub);
    return data;
  } catch {
    setCurrentUser(null);
    return null;
  }
}
