// static/js/main.js
const API_BASE = '/api';

// ==================== ОСНОВНАЯ ФУНКЦИЯ SETUP ====================
function setupForms() {
    console.log('Настройка обработчиков форм...');

    // Форма логина
    const loginForm = document.querySelector('#loginForm form');
    if (loginForm) {
        loginForm.addEventListener('submit', handleLogin);
    }

    // Форма загрузки файла
    const uploadForm = document.getElementById('uploadForm');
    if (uploadForm) {
        uploadForm.addEventListener('submit', handleFileUpload);
    }

    // Форма смены пароля
    const changePassForm = document.getElementById('changePassForm');
    if (changePassForm) {
        changePassForm.addEventListener('submit', handleChangePassword);
    }

    // Кнопки
    const logoutBtn = document.getElementById('logoutBtn');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', logout);
    }

    const refreshBtn = document.getElementById('refreshBtn');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', loadFileList);
    }

    console.log('Все формы настроены');
}

// ==================== АУТЕНТИФИКАЦИЯ ====================

function switchAuthTab(tab) {
    const loginForm = document.getElementById('loginForm');
    const registerForm = document.getElementById('registerForm');
    const loginTabBtn = document.getElementById('loginTabBtn');
    const registerTabBtn = document.getElementById('registerTabBtn');
    const authSubtitle = document.getElementById('authSubtitle');

    if (tab === 'login') {
        loginForm.style.display = 'block';
        registerForm.style.display = 'none';
        loginTabBtn.classList.add('active');
        registerTabBtn.classList.remove('active');
        authSubtitle.textContent = 'Вход в систему';
    } else {
        loginForm.style.display = 'none';
        registerForm.style.display = 'block';
        loginTabBtn.classList.remove('active');
        registerTabBtn.classList.add('active');
        authSubtitle.textContent = 'Регистрация нового пользователя';

        document.getElementById('registerForm').reset();
    }
}

function add2FAButton() {
    console.log('[DEBUG] add2FAButton вызвана');

    const userInfo = document.querySelector('.user-info') ||
        document.getElementById('userInfo') ||
        document.querySelector('.header') ||
        document.querySelector('[class*="user"]');

    if (!userInfo) {
        console.warn('[DEBUG] Контейнер для кнопки НЕ НАЙДЕН');
        return;
    }

    console.log('[DEBUG] Контейнер найден:', userInfo);

    // Удаляем старую кнопку, если есть (чтобы не дублировать)
    const oldBtn = userInfo.querySelector('#setup2faDashboardBtn');
    if (oldBtn) oldBtn.remove();

    const btn = document.createElement('button');
    btn.id = 'setup2faDashboardBtn';
    btn.textContent = 'Настроить 2FA';
    btn.className = 'btn btn-outline-primary ms-2';
    btn.style.marginLeft = '10px';
    btn.style.padding = '8px 16px';

    // Привязываем клик с отладкой
    btn.onclick = function () {
        console.log('[DEBUG] Клик по кнопке 2FA — вызываем handleSetup2FA');
        handleSetup2FA();
    };

    // Вставляем перед кнопкой "Выйти"
    const logoutBtn = userInfo.querySelector('.btn-danger, [onclick*="logout"]');
    if (logoutBtn) {
        userInfo.insertBefore(btn, logoutBtn);
    } else {
        userInfo.appendChild(btn);
    }

    console.log('[DEBUG] Кнопка добавлена и обработчик привязан');
}

async function handleLogin(event) {
    event.preventDefault();

    const username = document.getElementById('loginUsername').value.trim();
    const password = document.getElementById('loginPassword').value;
    const otpCode = document.getElementById('loginOtpCode')?.value || '';

    if (!username || !password) {
        showNotification('Введите логин и пароль', 'error');
        return;
    }

    try {
        const formData = new URLSearchParams({ username, password });
        if (otpCode) formData.append('otp_code', otpCode);

        const response = await fetch(`${API_BASE}/auth/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: formData,
            credentials: 'include'
        });

        if (!response.ok) {
            const err = await response.json();

            if (response.status === 400 && err.detail === 'Требуется код 2FA') {
                document.getElementById('loginOtpGroup').style.display = 'block';
                showNotification('Введите код 2FA', 'info');
                return;
            }
            if (response.status === 429) {
                showNotification('Слишком много попыток. Подождите 1 минуту', 'error');
                return;
            }

            throw new Error(err.detail || 'Ошибка входа');
        }

        const data = await response.json();

        showNotification(`Добро пожаловать, ${data.username}!`, 'success');
        document.getElementById('currentUsername').textContent = data.username;

        document.getElementById('authForm').style.display = 'none';
        document.getElementById('mainApp').style.display = 'block';

        loadFileList();

        // Добавляем кнопку 2FA в хедер/дашборд
        add2FAButton();

    } catch (error) {
        showNotification(`Ошибка входа: ${error.message}`, 'error');
    }
}

async function handleRegister(event) {
    event.preventDefault();

    const username = document.getElementById('registerUsername').value.trim();
    const email = document.getElementById('registerEmail').value.trim();
    const password = document.getElementById('registerPassword').value;
    const confirmPassword = document.getElementById('registerConfirmPassword').value;
    const agreeTerms = document.getElementById('registerAgreeTerms').checked;

    // Валидация
    if (!username || !email || !password || !confirmPassword) {
        showNotification('Заполните все поля', 'error');
        return;
    }

    if (username.length < 3 || username.length > 50) {
        showNotification('Логин от 3 до 50 символов', 'error');
        return;
    }

    if (!/^[a-zA-Z0-9_]+$/.test(username)) {
        showNotification('Логин: только буквы, цифры, подчёркивание', 'error');
        return;
    }

    if (password.length < 8) {
        showNotification('Пароль минимум 8 символов', 'error');
        return;
    }

    if (password !== confirmPassword) {
        showNotification('Пароли не совпадают', 'error');
        return;
    }

    if (!agreeTerms) {
        showNotification('Примите условия использования', 'error');
        return;
    }

    try {
        const response = await fetch(`${API_BASE}/auth/register`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, email, password }),
            credentials: 'include'
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || 'Ошибка регистрации');
        }

        const data = await response.json();

        showNotification('Регистрация успешна! Теперь войдите.', 'success');

        // Блок с рекомендацией 2FA
        const successBlock = document.createElement('div');
        successBlock.className = 'alert alert-success mt-3';
        successBlock.innerHTML = `
            <p>Аккаунт создан! Логин: <strong>${data.username}</strong></p>
            <p>Для безопасности включите 2FA.</p>
            
        `;

        // Создаём кнопку отдельно (чтобы сразу иметь ссылку)
        const setupBtn = document.createElement('button');
        setupBtn.className = 'btn btn-primary mt-2';
        setupBtn.textContent = 'Настроить 2FA сейчас';

        // Привязываем обработчик сразу
        setupBtn.addEventListener('click', async () => {
            try {
                const checkResp = await fetch('/api/whoami', { credentials: 'include' });
                if (!checkResp.ok) {
                    showNotification('Сначала войдите в аккаунт', 'warning');
                    switchAuthTab('login');
                    return;
                }
                handleSetup2FA();
            } catch {
                showNotification('Сначала войдите в аккаунт', 'warning');
                switchAuthTab('login');
            }
        });

        successBlock.appendChild(setupBtn);

        const registerForm = document.getElementById('registerForm');
        registerForm.after(successBlock);

        switchAuthTab('login');
        document.getElementById('loginUsername').value = username;

    } catch (error) {
        showNotification(`Ошибка: ${error.message}`, 'error');
    }
}

async function logout() {
    if (!confirm('Вы уверены, что хотите выйти?')) return;

    try {
        const response = await fetch(`${API_BASE}/auth/logout`, {
            method: 'POST',
            credentials: 'include'
        });

        if (response.ok) {
            document.getElementById('authForm').style.display = 'block';
            document.getElementById('mainApp').style.display = 'none';

            const fileList = document.getElementById('fileList');
            if (fileList) fileList.innerHTML = '';

            document.getElementById('loginForm').reset();
            document.getElementById('registerForm').reset();
            document.getElementById('loginOtpGroup').style.display = 'none';

            showNotification('Вы успешно вышли из системы', 'info');
        } else {
            showNotification('Ошибка выхода', 'error');
        }
    } catch (e) {
        showNotification('Ошибка выхода: ' + e.message, 'error');
    }
}

// ────────────────────────────────────────────────
// 2FA модалка — глобальные переменные для элементов
// ────────────────────────────────────────────────
let twoFaModal = null;
let twoFaMsg = null;
let twoFaInst = null;
let twoFaCode = null;
let twoFaQr = null;

// Запуск настройки 2FA
async function handleSetup2FA() {
    console.log('[DEBUG] handleSetup2FA запущена');

    try {
        console.log('[DEBUG] Отправляем запрос на /setup-2fa');
        const response = await fetch('/api/auth/setup-2fa', {
            method: 'POST',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' }
        });

        console.log('[DEBUG] Ответ получен, статус:', response.status);

        if (!response.ok) {
            if (response.status === 401) {
                showNotification('Сессия истекла. Войдите заново.', 'error');
                switchAuthTab('login');
            } else {
                const err = await response.json();
                showNotification(err.detail || 'Ошибка настройки 2FA', 'error');
            }
            return;
        }

        const data = await response.json();
        console.log('[DEBUG] Данные от сервера:', data);

        show2FASetupModal(data.otp_url, data.message, data.instructions || []);

    } catch (err) {
        console.error('[DEBUG] Ошибка в handleSetup2FA:', err);
        showNotification('Ошибка: ' + err.message, 'error');
    }
}

// Создание и показ модалки
function show2FASetupModal(otpUrl, message, instructions) {
    if (!twoFaModal) {
        // Создаём модалку один раз
        twoFaModal = document.createElement('div');
        twoFaModal.id = 'twoFaModal';
        twoFaModal.className = 'modal';
        twoFaModal.innerHTML = `
             <div class="modal-content">
                 <span class="close" onclick="close2FAModal()">×</span>
                 <h2>Настройка 2FA</h2>
                 <p id="twoFaMsg"></p>
                 <div id="qrcode" style="margin:20px auto; text-align:center;"></div>
                 <ul id="twoFaInst"></ul>
                 <label for="twoFaCode">Код из приложения:</label>
                 <input type="text" id="twoFaCode" maxlength="6" placeholder="123456" 
                        style="width:100%; text-align:center; font-size:1.5em; margin:10px 0;">
                 <button onclick="verify2FACode()" class="btn btn-success" style="width:100%;">
                     Подтвердить
                 </button>
             </div>
         `;
        document.body.appendChild(twoFaModal);

        // Сохраняем ссылки на элементы
        twoFaMsg = document.getElementById('twoFaMsg');
        twoFaInst = document.getElementById('twoFaInst');
        twoFaCode = document.getElementById('twoFaCode');
        twoFaQr = document.getElementById('qrcode');
    }

    // Заполняем содержимое через сохранённые ссылки
    twoFaMsg.textContent = message;

    twoFaInst.innerHTML = instructions.map(i => `<li>${i}</li>`).join('');

    twoFaQr.innerHTML = '';

    new QRCode(twoFaQr, {
        text: otpUrl,
        width: 240,
        height: 240,
        colorDark: "#000000",
        colorLight: "#ffffff",
        correctLevel: QRCode.CorrectLevel.H
    });

    twoFaModal.style.display = 'block';
}

function close2FAModal() {
    if (twoFaModal) {
        twoFaModal.style.display = 'none';
        if (twoFaCode) twoFaCode.value = '';  // очищаем поле
    }
}

async function verify2FACode() {
    const code = twoFaCode?.value.trim();

    if (!code || code.length !== 6 || !/^\d{6}$/.test(code)) {
        showNotification('Введите 6 цифр', 'error');
        return;
    }

    try {
        const response = await fetch('/api/auth/verify-2fa-setup', {
            method: 'POST',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ code })
        });

        const data = await response.json();

        if (response.ok) {
            showNotification('2FA успешно настроена!', 'success');
            close2FAModal();
        } else {
            showNotification(data.detail || 'Неверный код', 'error');
        }
    } catch (err) {
        showNotification('Ошибка проверки: ' + err.message, 'error');
    }
}

// ==================== УПРАВЛЕНИЕ ФАЙЛАМИ ====================

async function loadFileList() {
    const fileList = document.getElementById('fileList');
    if (!fileList) return;

    fileList.innerHTML = '<div class="loading">⏳ Загрузка...</div>';

    try {
        const response = await fetch(`${API_BASE}/list`, {
            credentials: 'include'
        });

        if (!response.ok) {
            if (response.status === 401 || response.status === 403) {
                document.getElementById('authForm').style.display = 'block';
                document.getElementById('mainApp').style.display = 'none';
                showNotification('Пожалуйста, войдите в систему', 'error');
                return;
            }
            const err = await response.json();
            throw new Error(err.detail || `Ошибка ${response.status}`);
        }

        const data = await response.json();

        if (data.count === 0) {
            fileList.innerHTML = '<div class="empty">📭 Нет загруженных файлов</div>';
            return;
        }

        let html = '';
        data.files.forEach(file => {
            const encryptedName = file.name;
            const originalName = file.original_name || encryptedName.replace(/^[a-f0-9]+_/, '').replace('.age$', '');
            const fileId = file.id;

            html += `
                <div class="file-item">
                    <div class="file-info">
                        <div class="file-name">📄 ${originalName}</div>
                        <div class="file-size">📏 ${formatBytes(file.size)}</div>
                        ${file.patient_id ? `<div class="patient-id">🆔 Пациент: ${file.patient_id}</div>` : ''}
                        <div class="file-id">🔐 <small>${encryptedName}</small></div>
                    </div>
                    <div class="file-actions">
                        ${file.download_token ? `
                            <a href="${file.download_url}" target="_blank" class="btn-secondary btn-small">📥 Скачать</a>
                        ` : `
                            <button onclick="downloadFile('${encryptedName}')" class="btn-secondary btn-small">📥 Скачать</button>
                        `}
                        <button onclick="deleteUserFile('${encryptedName}', '${originalName}')" class="btn-danger btn-small">🗑️ Удалить</button>
                    </div>
                </div>
            `;
        });

        fileList.innerHTML = html;

    } catch (error) {
        fileList.innerHTML = `<div class="error">❌ ${error.message}</div>`;
    }
}

async function handleFileUpload(event) {
    event.preventDefault();

    const form = event.target;
    const fileInput = form.querySelector('input[type="file"]');
    const submitBtn = form.querySelector('button[type="submit"]');

    if (!fileInput || !fileInput.files.length) {
        alert('❌ Выберите файл');
        return;
    }

    const file = fileInput.files[0];
    const originalBtnText = submitBtn.textContent;

    submitBtn.textContent = '⏳ Шифрование...';
    submitBtn.disabled = true;

    try {
        const formData = new FormData();
        formData.append('file', file);

        const response = await fetch(`${API_BASE}/upload`, {
            method: 'POST',
            body: formData,
            credentials: 'include'
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || 'Ошибка загрузки');
        }

        const data = await response.json();

        if (data.download_url) {
            showUploadResult(data);
        } else {
            alert(`✅ Файл "${data.original_name}" успешно загружен!`);
        }

        loadFileList();
        fileInput.value = '';

    } catch (error) {
        alert(`❌ ${error.message}`);
    } finally {
        submitBtn.textContent = originalBtnText;
        submitBtn.disabled = false;
    }
}

async function downloadFile(encryptedFilename) {
    try {
        const response = await fetch(
            `${API_BASE}/download?filename=${encodeURIComponent(encryptedFilename)}`,
            { credentials: 'include' }
        );

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || `Ошибка ${response.status}`);
        }

        const blob = await response.blob();
        const originalName = encryptedFilename.replace(/^[a-f0-9]+_/, '').replace('.age$', '');

        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = originalName;
        document.body.appendChild(a);
        a.click();

        setTimeout(() => {
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);
        }, 100);

    } catch (error) {
        alert(`❌ Ошибка скачивания: ${error.message}`);
    }
}

async function handleChangePassword(event) {
    event.preventDefault();

    const oldPass = document.getElementById('oldPassword')?.value;
    const newPass = document.getElementById('newPassword')?.value;
    const confirmPass = document.getElementById('confirmPassword')?.value;

    if (!oldPass || !newPass) {
        alert('Заполните все поля');
        return;
    }

    if (newPass !== confirmPass) {
        alert('Новый пароль и подтверждение не совпадают');
        return;
    }

    try {
        const response = await fetch(`${API_BASE}/auth/change-password`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                old_password: oldPass,
                new_password: newPass
            }),
            credentials: 'include'
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || 'Ошибка смены пароля');
        }

        alert('✅ Пароль успешно изменён');
        event.target.reset();

    } catch (error) {
        alert(`❌ ${error.message}`);
    }
}

async function deleteUserFile(filename, originalName) {
    if (!confirm(`Вы уверены, что хотите удалить файл "${originalName || filename}"?`)) {
        return;
    }

    try {
        const formData = new URLSearchParams();
        formData.append('filename', filename);
        formData.append('confirm', 'true');

        const response = await fetch(`${API_BASE}/delete-user-file`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: formData,
            credentials: 'include'
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || 'Ошибка удаления');
        }

        const result = await response.json();
        showNotification(result.message, 'success');
        loadFileList();

    } catch (error) {
        showNotification(`Ошибка: ${error.message}`, 'error');
    }
}

// ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================

function showUploadResult(data) {
    const resultDiv = document.getElementById('uploadResult');
    if (!resultDiv) return;

    resultDiv.innerHTML = '';

    const expiresDate = data.expires_at ? new Date(data.expires_at).toLocaleString('ru-RU') : 'Не указано';

    const linkContainer = document.createElement('div');
    linkContainer.className = 'download-link';
    linkContainer.innerHTML = `
        <p><strong>✅ Файл "${data.original_name}" загружен!</strong></p>
        <p><strong>Ссылка для скачивания:</strong></p>
        <input type="text" value="${data.download_url}" readonly style="width: 100%; padding: 8px; margin-bottom: 10px;">
        <button onclick="copyToClipboard(this.previousElementSibling)">📋 Копировать</button>
        <p><small>⏰ Срок действия: ${expiresDate} | 🔢 Макс. скачиваний: ${data.max_downloads || 'Не ограничено'}</small></p>
    `;

    resultDiv.appendChild(linkContainer);

    setTimeout(() => {
        if (linkContainer.parentNode) linkContainer.remove();
    }, 30000);
}

function copyToClipboard(inputElement) {
    inputElement.select();
    document.execCommand('copy');
    alert('✅ Ссылка скопирована в буфер обмена!');
}

function formatBytes(bytes, decimals = 2) {
    if (bytes === 0) return '0 Bytes';

    const k = 1024;
    const dm = decimals < 0 ? 0 : decimals;
    const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];

    const i = Math.floor(Math.log(bytes) / Math.log(k));

    return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
}

function showNotification(message, type = 'info') {
    let container = document.getElementById('notificationContainer');
    if (!container) {
        container = document.createElement('div');
        container.id = 'notificationContainer';
        container.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            z-index: 9999;
        `;
        document.body.appendChild(container);
    }

    const notification = document.createElement('div');
    notification.style.cssText = `
        background: ${type === 'error' ? '#ff4444' : type === 'success' ? '#00C851' : '#33b5e5'};
        color: white;
        padding: 15px 20px;
        margin-bottom: 10px;
        border-radius: 5px;
        box-shadow: 0 3px 6px rgba(0,0,0,0.16);
        animation: slideIn 0.3s ease;
        max-width: 300px;
    `;
    notification.textContent = message;

    container.appendChild(notification);

    setTimeout(() => {
        notification.style.animation = 'slideOut 0.3s ease';
        setTimeout(() => {
            container.removeChild(notification);
        }, 300);
    }, 5000);
}

// Анимации
const style = document.createElement('style');
style.textContent = `
    @keyframes slideIn {
        from { transform: translateX(100%); opacity: 0; }
        to { transform: translateX(0); opacity: 1; }
    }
    @keyframes slideOut {
        from { transform: translateX(0); opacity: 1; }
        to { transform: translateX(100%); opacity: 0; }
    }
`;
document.head.appendChild(style);

// ==================== ИНИЦИАЛИЗАЦИЯ ====================
document.addEventListener('DOMContentLoaded', function () {
    // Пробуем сразу загрузить список файлов
    // Если не авторизованы — backend вернёт 401 → покажем форму логина
    loadFileList();

    setupForms();
});

// Автообновление списка каждые 30 секунд
setInterval(loadFileList, 30000);

// Экспорт функций
window.downloadFile = downloadFile;
window.copyToClipboard = copyToClipboard;