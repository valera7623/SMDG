// static/js/modules/auth.js

import { auth as authAPI }   from '../core/api.js';
import { setCurrentUser }    from '../core/state.js';
import { showNotification }  from '../utils/notifications.js';
import { validateUsername, validatePassword, isValidEmail, passwordStrength } from '../utils/validators.js';
import { setVisible }        from '../utils/dom.js';
import { loadFileList }      from './files.js';

const ADMIN_ROLES = new Set(['admin', 'super_admin']);

// ── Переменные для 2FA модалки (создаются один раз) ──────────────────────────
let _twoFaModal = null;
let _twoFaMsg   = null;
let _twoFaInst  = null;
let _twoFaCode  = null;
let _twoFaQr    = null;

function _setAdminNavigationVisible(role) {
    const isAdmin = ADMIN_ROLES.has(role);
    document.querySelectorAll('[data-admin-only="true"]').forEach((el) => {
        el.hidden = !isAdmin;
    });
}

async function _refreshCurrentUser() {
    try {
        const data = await authAPI.whoami();
        setCurrentUser(data.sub);
        const usernameEl = document.getElementById('currentUsername');
        if (usernameEl) usernameEl.textContent = data.sub;
        _setAdminNavigationVisible(data.role);
        setVisible(document.getElementById('authForm'), false);
        setVisible(document.getElementById('mainApp'), true);
        return data;
    } catch (error) {
        setCurrentUser(null);
        _setAdminNavigationVisible(null);
        setVisible(document.getElementById('authForm'), true);
        setVisible(document.getElementById('mainApp'), false);
        if (error.status === 401 || error.status === 403) return;
        console.warn('Не удалось получить текущего пользователя:', error);
        return null;
    }
}

// ── Переключение вкладок Login / Register ─────────────────────────────────────
export function switchAuthTab(tab) {
    const loginForm    = document.getElementById('loginForm');
    const registerForm = document.getElementById('registerForm');
    const loginTabBtn  = document.getElementById('loginTabBtn');
    const regTabBtn    = document.getElementById('registerTabBtn');
    const subtitle     = document.getElementById('authSubtitle');

    const isLogin = tab === 'login';

    setVisible(loginForm,    isLogin);
    setVisible(registerForm, !isLogin);

    loginTabBtn?.classList.toggle('active', isLogin);
    regTabBtn?.classList.toggle('active',   !isLogin);

    if (subtitle) {
        subtitle.textContent = isLogin ? 'Вход в систему' : 'Регистрация нового пользователя';
    }

    if (!isLogin) document.getElementById('registerForm')?.reset();
}

// ── Login ─────────────────────────────────────────────────────────────────────
export async function handleLogin(event) {
    event.preventDefault();

    const username = document.getElementById('loginUsername').value.trim();
    const password = document.getElementById('loginPassword').value;
    const otpCode  = document.getElementById('loginOtpCode')?.value || '';

    if (!username || !password) {
        showNotification('Введите логин и пароль', 'error');
        return;
    }

    try {
        const response = await authAPI.login(username, password, otpCode);

        if (!response.ok) {
            const err = await response.json().catch(() => ({}));

            if (response.status === 400 && err.detail === 'Требуется код 2FA') {
                setVisible(document.getElementById('loginOtpGroup'), true);
                showNotification('Введите код 2FA из приложения', 'info');
                return;
            }
            if (response.status === 429) {
                showNotification('Слишком много попыток. Подождите 1 минуту.', 'error');
                return;
            }
            throw new Error(err.detail || 'Ошибка входа');
        }

        const data = await response.json();

        setCurrentUser(data.username);
        document.getElementById('currentUsername').textContent = data.username;
        _setAdminNavigationVisible(data.role);

        setVisible(document.getElementById('authForm'), false);
        setVisible(document.getElementById('mainApp'),  true);

        showNotification(`Добро пожаловать, ${data.username}!`, 'success');

        loadFileList();
        _attach2FAButton();

    } catch (error) {
        if (error.status === 401 || error.status === 403) return; // уже обработано в api.js
        showNotification(`Ошибка входа: ${error.message}`, 'error');
    }
}

// ── Register ──────────────────────────────────────────────────────────────────
export async function handleRegister(event) {
    event.preventDefault();

    const username        = document.getElementById('registerUsername').value.trim();
    const email           = document.getElementById('registerEmail').value.trim();
    const password        = document.getElementById('registerPassword').value;
    const confirmPassword = document.getElementById('registerConfirmPassword').value;
    const agreeTerms      = document.getElementById('registerAgreeTerms').checked;

    // Валидация
    const usernameCheck = validateUsername(username);
    if (!usernameCheck.valid) { showNotification(usernameCheck.error, 'error'); return; }

    if (!email || !isValidEmail(email)) {
        showNotification('Введите корректный email', 'error');
        return;
    }

    const passwordCheck = validatePassword(password);
    if (!passwordCheck.valid) { showNotification(passwordCheck.error, 'error'); return; }

    if (password !== confirmPassword) {
        showNotification('Пароли не совпадают', 'error');
        return;
    }

    if (!agreeTerms) {
        showNotification('Примите условия использования', 'error');
        return;
    }

    try {
        const data = await authAPI.register(username, email, password);

        showNotification('Регистрация успешна! Теперь войдите.', 'success');

        switchAuthTab('login');
        const loginInput = document.getElementById('loginUsername');
        if (loginInput) loginInput.value = username;

        // Подсказка про 2FA
        _showRegisterSuccess(data.username);

    } catch (error) {
        showNotification(`Ошибка: ${error.message}`, 'error');
    }
}

function _showRegisterSuccess(username) {
    const block = document.createElement('div');
    block.className = 'alert alert-success mt-3';
    block.style.cssText = 'background:#d4edda;border:1px solid #c3e6cb;padding:15px;border-radius:6px;margin-top:15px;';
    block.innerHTML = `<p>Аккаунт <strong>${username}</strong> создан!</p><p>Для безопасности рекомендуем включить 2FA.</p>`;

    const loginSection = document.getElementById('loginForm');
    if (loginSection) loginSection.after(block);
    setTimeout(() => block.remove(), 8000);
}

// ── Logout ────────────────────────────────────────────────────────────────────
export async function logout() {
    if (!confirm('Вы уверены, что хотите выйти?')) return;

    try {
        const response = await authAPI.logout();
        if (response.ok) {
            setCurrentUser(null);
            _setAdminNavigationVisible(null);

            setVisible(document.getElementById('authForm'), true);
            setVisible(document.getElementById('mainApp'),  false);

            const fileList = document.getElementById('fileList');
            if (fileList) fileList.innerHTML = '';

            document.getElementById('loginForm')?.reset();
            document.getElementById('registerForm')?.reset();
            setVisible(document.getElementById('loginOtpGroup'), false);

            showNotification('Вы вышли из системы', 'info');
        } else {
            showNotification('Ошибка выхода', 'error');
        }
    } catch (e) {
        showNotification('Ошибка выхода: ' + e.message, 'error');
    }
}

// ── Сила пароля ───────────────────────────────────────────────────────────────
export function updatePasswordStrength(inputEl) {
    const strength = passwordStrength(inputEl.value);
    const bar      = document.querySelector('.strength-bar');
    if (!bar) return;

    const colors = ['#dc3545', '#fd7e14', '#ffc107', '#20c997', '#28a745'];
    bar.style.width           = `${strength * 25}%`;
    bar.style.backgroundColor = colors[strength] ?? colors[0];
}

// ── 2FA ───────────────────────────────────────────────────────────────────────

function _attach2FAButton() {
    const userInfo = document.querySelector('.user-info');
    if (!userInfo) return;

    let btn = document.getElementById('setup2faDashboardBtn');
    if (!btn) {
        btn = document.createElement('button');
        btn.id        = 'setup2faDashboardBtn';
        btn.className = 'btn btn-outline-primary';
        btn.textContent = 'Настроить 2FA';
        btn.style.cssText = 'margin-left:10px; padding:8px 16px;';
        btn.addEventListener('click', handleSetup2FA);

        const logoutBtn = userInfo.querySelector('.btn-danger, [data-action="logout"]');
        logoutBtn ? userInfo.insertBefore(btn, logoutBtn) : userInfo.appendChild(btn);
    }
}

export async function handleSetup2FA() {
    try {
        const data = await authAPI.setup2FA();
        _show2FAModal(data.otp_url, data.message, data.instructions || []);
    } catch (error) {
        if (error.status === 401) {
            showNotification('Сессия истекла. Войдите заново.', 'error');
            switchAuthTab('login');
        } else {
            showNotification(error.message || 'Ошибка настройки 2FA', 'error');
        }
    }
}

function _show2FAModal(otpUrl, message, instructions) {
    if (!_twoFaModal) {
        _twoFaModal = document.createElement('div');
        _twoFaModal.className = 'modal';
        _twoFaModal.innerHTML = `
            <div class="modal-content">
                <span class="close" id="close2FABtn">&times;</span>
                <h2>Настройка 2FA</h2>
                <p id="twoFaMsg"></p>
                <div id="twoFaQr" style="margin:20px auto;text-align:center;"></div>
                <ul id="twoFaInst"></ul>
                <label for="twoFaCode">Код из приложения:</label>
                <input type="text" id="twoFaCode" maxlength="6" placeholder="123456"
                       style="width:100%;text-align:center;font-size:1.5em;margin:10px 0;">
                <button id="verify2FABtn" class="btn-success" style="width:100%;">Подтвердить</button>
            </div>
        `;
        document.body.appendChild(_twoFaModal);

        _twoFaMsg  = document.getElementById('twoFaMsg');
        _twoFaInst = document.getElementById('twoFaInst');
        _twoFaCode = document.getElementById('twoFaCode');
        _twoFaQr   = document.getElementById('twoFaQr');

        document.getElementById('close2FABtn').addEventListener('click', close2FAModal);
        document.getElementById('verify2FABtn').addEventListener('click', verify2FACode);
    }

    _twoFaMsg.textContent = message;
    _twoFaInst.innerHTML  = instructions.map(i => `<li>${i}</li>`).join('');
    _twoFaQr.innerHTML    = '';

    /* global QRCode */
    new QRCode(_twoFaQr, {
        text:         otpUrl,
        width:        240,
        height:       240,
        colorDark:    '#000000',
        colorLight:   '#ffffff',
        correctLevel: QRCode.CorrectLevel.H,
    });

    _twoFaModal.style.display = 'block';
}

export function close2FAModal() {
    if (_twoFaModal) _twoFaModal.style.display = 'none';
    if (_twoFaCode)  _twoFaCode.value = '';
}

export async function verify2FACode() {
    const code = _twoFaCode?.value.trim();
    if (!code || !/^\d{6}$/.test(code)) {
        showNotification('Введите 6 цифр', 'error');
        return;
    }

    try {
        await authAPI.verify2FA(code);
        showNotification('2FA успешно настроена!', 'success');
        close2FAModal();
    } catch (error) {
        showNotification(error.message || 'Неверный код', 'error');
    }
}

// ── Инициализация ─────────────────────────────────────────────────────────────

/**
 * Вызывается из main.js после DOMContentLoaded.
 * Привязывает обработчики форм и проверяет сессию.
 */
export async function initAuth() {
    document.getElementById('loginForm')
        ?.addEventListener('submit', handleLogin);

    document.getElementById('registerForm')
        ?.addEventListener('submit', handleRegister);

    // Кнопки в header
    const logoutBtn = document.getElementById('logoutBtn');
    if (logoutBtn) logoutBtn.addEventListener('click', logout);

    // Сила пароля при вводе
    const passInput = document.getElementById('registerPassword');
    if (passInput) passInput.addEventListener('input', () => updatePasswordStrength(passInput));

    const current = await _refreshCurrentUser();

    if (current) {
        loadFileList();
        _attach2FAButton();
    }
}
