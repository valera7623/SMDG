// static/js/main.js
const API_BASE = '/api';

let JWT_TOKEN = localStorage.getItem('token') || null;

function getAuthHeaders() {
    if (JWT_TOKEN) {
        return { 'Authorization': `Bearer ${JWT_TOKEN}` };
    }
    return {};
}

// ==================== ОСНОВНАЯ ФУНКЦИЯ SETUP ====================
function setupForms() {
    console.log('Настройка обработчиков форм...');

    // Форма логина
    const loginForm = document.querySelector('#loginForm form');
    if (loginForm) {
        loginForm.addEventListener('submit', handleLogin);
    }

    // Форма загрузки файла (используем новый обработчик)
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

// Переключение между вкладками входа и регистрации
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

        // Сбрасываем форму регистрации
        document.getElementById('registerForm').reset();
    }
}

// Обработка входа
async function handleLogin(event) {
    event.preventDefault();

    const username = document.getElementById('loginUsername').value.trim();
    const password = document.getElementById('loginPassword').value;
    const otpCode = document.getElementById('loginOtpCode').value;

    if (!username || !password) {
        showNotification('Введите логин и пароль', 'error');
        return;
    }

    try {
        const formData = new URLSearchParams({ username, password });
        if (otpCode) {
            formData.append('otp_code', otpCode);
        }

        const response = await fetch(`${API_BASE}/auth/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: formData
        });

        if (!response.ok) {
            const err = await response.json();

            // Если ошибка связана с 2FA
            if (response.status === 400 && err.detail === 'Требуется код 2FA') {
                document.getElementById('loginOtpGroup').style.display = 'block';
                showNotification('Введите код двухфакторной аутентификации', 'info');
                return;
            }

            throw new Error(err.detail || 'Ошибка входа');
        }

        const data = await response.json();
        JWT_TOKEN = data.access_token;
        localStorage.setItem('token', JWT_TOKEN);
        localStorage.setItem('username', data.username);

        // Скрываем поле 2FA если оно было показано
        document.getElementById('loginOtpGroup').style.display = 'none';

        showNotification(`Добро пожаловать, ${data.username}!`, 'success');
        document.getElementById('currentUsername').textContent = data.username;

        document.getElementById('authForm').style.display = 'none';
        document.getElementById('mainApp').style.display = 'block';
        loadFileList();

        // Если 2FA только что включен, показываем настройку
        if (data['2fa_enabled'] && data['2fa_setup_required']) {
            showOtpSetup(data['otp_secret'], data['otp_url']);
        }

    } catch (error) {
        showNotification(`Ошибка входа: ${error.message}`, 'error');
    }
}

// Обработка регистрации
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
        showNotification('Логин должен быть от 3 до 50 символов', 'error');
        return;
    }

    if (!/^[a-zA-Z0-9_]+$/.test(username)) {
        showNotification('Логин может содержать только буквы, цифры и подчеркивание', 'error');
        return;
    }

    if (password.length < 8) {
        showNotification('Пароль должен быть не менее 8 символов', 'error');
        return;
    }

    if (password !== confirmPassword) {
        showNotification('Пароли не совпадают', 'error');
        return;
    }

    if (!agreeTerms) {
        showNotification('Необходимо принять условия использования', 'error');
        return;
    }

    try {
        const response = await fetch(`${API_BASE}/auth/register`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                username,
                email,
                password
            })
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || 'Ошибка регистрации');
        }

        const data = await response.json();

        showNotification('Регистрация успешна! Теперь вы можете войти.', 'success');

        // Переключаемся на вкладку входа
        switchAuthTab('login');

        // Предзаполняем логин
        document.getElementById('loginUsername').value = username;

        // Показываем сообщение о 2FA если оно было сгенерировано
        if (data.otp_secret) {
            showOtpSetup(data.otp_secret, data.otp_url);
        }

    } catch (error) {
        showNotification(`Ошибка регистрации: ${error.message}`, 'error');
    }
}

// Проверка сложности пароля в реальном времени
document.getElementById('registerPassword')?.addEventListener('input', function (e) {
    const password = e.target.value;
    const strengthBar = document.querySelector('.strength-bar');

    if (!strengthBar) return;

    // Оценка сложности пароля
    let strength = 0;

    if (password.length >= 8) strength += 1;
    if (password.length >= 12) strength += 1;
    if (/[A-Z]/.test(password)) strength += 1;
    if (/[0-9]/.test(password)) strength += 1;
    if (/[^A-Za-z0-9]/.test(password)) strength += 1;

    // Обновление индикатора
    const percentage = (strength / 5) * 100;
    strengthBar.style.width = percentage + '%';

    if (strength <= 2) {
        strengthBar.style.backgroundColor = '#ff4444';
    } else if (strength <= 3) {
        strengthBar.style.backgroundColor = '#ffaa00';
    } else {
        strengthBar.style.backgroundColor = '#00C851';
    }
});

// Показать настройку 2FA
function showOtpSetup(secret, otpUrl) {
    const modal = document.getElementById('otpModal');
    const content = document.getElementById('otpSetupContent');

    content.innerHTML = `
        <p>Для повышения безопасности рекомендуется настроить двухфакторную аутентификацию.</p>
        
        <div class="otp-secret">
            <strong>Секретный ключ:</strong>
            <code>${secret}</code>
            <button onclick="copyToClipboard('${secret}')" class="btn-small">📋 Копировать</button>
        </div>
        
        <div class="qr-code">
            <img src="https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=${encodeURIComponent(otpUrl)}" 
                 alt="QR Code для 2FA">
        </div>
        
        <p>Отсканируйте QR-код в приложении Google Authenticator или подобном, или введите ключ вручную.</p>
        
        <div class="form-group">
            <label>Введите код для подтверждения:</label>
            <input type="text" id="verifyOtpCode" maxlength="6" pattern="[0-9]{6}" placeholder="6-значный код">
        </div>
        
        <div class="form-actions">
            <button onclick="verifyOtpSetup()" class="btn-primary">Подтвердить</button>
            <button onclick="closeOtpModal()" class="btn-secondary">Позже</button>
        </div>
    `;

    modal.style.display = 'block';
}

// Закрыть модальное окно
function closeOtpModal() {
    document.getElementById('otpModal').style.display = 'none';
}

// Копирование в буфер обмена
function copyToClipboard(text) {
    navigator.clipboard.writeText(text).then(() => {
        showNotification('Секретный ключ скопирован', 'success');
    });
}

// Показать условия использования
function showTerms() {
    alert('Условия использования:\n\n1. Система предназначена только для медицинских данных\n2. Все данные шифруются\n3. Не передавайте файлы третьим лицам\n4. Используйте надежные пароли\n5. Включите двухфакторную аутентификацию для безопасности');
}

// Показать восстановление пароля
function showForgotPassword() {
    alert('Функция восстановления пароля будет доступна в ближайшее время.\n\nОбратитесь к администратору для сброса пароля.');
}

// Система уведомлений
function showNotification(message, type = 'info') {
    // Создаем контейнер для уведомлений если его нет
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

    // Создаем уведомление
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

    // Удаляем через 5 секунд
    setTimeout(() => {
        notification.style.animation = 'slideOut 0.3s ease';
        setTimeout(() => {
            container.removeChild(notification);
        }, 300);
    }, 5000);
}

// Добавляем анимации
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

function logout() {
    if (confirm('Вы уверены, что хотите выйти?')) {
        localStorage.removeItem('token');
        localStorage.removeItem('username');
        JWT_TOKEN = null;

        const authForm = document.getElementById('authForm');
        const mainApp = document.getElementById('mainApp');
        const fileList = document.getElementById('fileList');

        if (authForm) authForm.style.display = 'block';
        if (mainApp) mainApp.style.display = 'none';
        if (fileList) fileList.innerHTML = '';

        // Сбрасываем формы
        document.getElementById('loginForm').reset();
        document.getElementById('registerForm').reset();
        document.getElementById('loginOtpGroup').style.display = 'none';

        showNotification('Вы успешно вышли из системы', 'info');
    }
}

// ==================== УПРАВЛЕНИЕ ФАЙЛАМИ ====================
async function loadFileList() {
    const fileList = document.getElementById('fileList');
    if (!fileList) return;

    fileList.innerHTML = '<div class="loading">⏳ Загрузка...</div>';

    try {
        const response = await fetch(`${API_BASE}/list`, {
            headers: getAuthHeaders()
        });

        if (!response.ok) {
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

            html += `
                <div class="file-item">
                    <div class="file-info">
                        <div class="file-name">📄 ${originalName}</div>
                        <div class="file-size">
                            📏 ${formatBytes(file.size)}<br>
                            🔐 <small>${encryptedName}</small>
                        </div>
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
            headers: getAuthHeaders(),
            body: formData
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || 'Ошибка загрузки');
        }

        const data = await response.json();

        // Показываем результат
        if (data.download_url) {
            showUploadResult(data);
        } else {
            alert(`✅ Файл "${data.original_name}" успешно загружен!`);
        }

        // Обновляем список
        loadFileList();

        // Очищаем поле
        fileInput.value = '';

    } catch (error) {
        alert(`❌ ${error.message}`);
    } finally {
        submitBtn.textContent = originalBtnText;
        submitBtn.disabled = false;
    }
}

function showUploadResult(data) {
    const resultDiv = document.getElementById('uploadResult');
    if (!resultDiv) {
        console.warn('Элемент #uploadResult не найден');
        return;
    }

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

    // Автоочистка через 30 секунд
    setTimeout(() => {
        if (linkContainer.parentNode) {
            linkContainer.remove();
        }
    }, 30000);
}

function copyToClipboard(inputElement) {
    inputElement.select();
    document.execCommand('copy');
    alert('✅ Ссылка скопирована в буфер обмена!');
}

async function downloadFile(encryptedFilename) {
    try {
        const response = await fetch(
            `${API_BASE}/download?filename=${encodeURIComponent(encryptedFilename)}`,
            { headers: getAuthHeaders() }
        );

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || `Ошибка ${response.status}`);
        }

        const blob = await response.blob();
        const originalName = encryptedFilename.replace(/^[a-f0-9]+_/, '').replace('.age$', '');

        // Создаем и скачиваем файл
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = originalName;
        document.body.appendChild(a);
        a.click();

        // Очистка
        setTimeout(() => {
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);
        }, 100);

    } catch (error) {
        alert(`❌ Ошибка скачивания: ${error.message}`);
    }
}

async function handleDownloadByName(event) {
    event.preventDefault();
    const input = document.querySelector('#downloadForm input[name="filename"]');
    const filename = input?.value.trim();

    if (filename) {
        await downloadFile(filename);
        if (input) input.value = '';
    } else {
        alert('Введите имя зашифрованного файла (с .age)');
    }
}

// ==================== СМЕНА ПАРОЛЯ ====================
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
            headers: {
                ...getAuthHeaders(),
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                old_password: oldPass,
                new_password: newPass
            })
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || 'Ошибка смены пароля');
        }

        alert('✅ Пароль успешно изменён');

        // Очищаем форму
        event.target.reset();

    } catch (error) {
        alert(`❌ ${error.message}`);
    }
}

async function uploadFile(file) {
    const formData = new FormData();
    formData.append("file", file);

    const progressContainer = document.createElement('div');
    progressContainer.innerHTML = '<progress value="0" max="100"></progress> <span>0%</span>';
    document.body.appendChild(progressContainer);

    try {
        const xhr = new XMLHttpRequest();
        xhr.open("POST", `${API_BASE}/upload`, true);
        xhr.setRequestHeader("Authorization", `Bearer ${JWT_TOKEN}`);

        xhr.upload.onprogress = (e) => {
            if (e.lengthComputable) {
                const percent = Math.round((e.loaded / e.total) * 100);
                progressContainer.querySelector('progress').value = percent;
                progressContainer.querySelector('span').textContent = `${percent}%`;
            }
        };

        xhr.onload = () => {
            if (xhr.status === 200) {
                alert('✅ Файл загружен');
                loadFileList();
            } else {
                alert('❌ Ошибка: ' + xhr.responseText);
            }
            progressContainer.remove();
        };

        xhr.send(formData);
    } catch (e) {
        alert('❌ ' + e.message);
        progressContainer.remove();
    }
}

// ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================
function formatBytes(bytes, decimals = 2) {
    if (bytes === 0) return '0 Bytes';

    const k = 1024;
    const dm = decimals < 0 ? 0 : decimals;
    const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];

    const i = Math.floor(Math.log(bytes) / Math.log(k));

    return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
}

// ==================== ИНИЦИАЛИЗАЦИЯ ====================
document.addEventListener('DOMContentLoaded', function () {
    // Проверка авторизации
    if (JWT_TOKEN) {
        const loginForm = document.getElementById('loginForm');
        const mainApp = document.getElementById('mainApp');

        if (loginForm) loginForm.style.display = 'none';
        if (mainApp) mainApp.style.display = 'block';

        loadFileList();
    }

    // Настройка всех форм
    setupForms();
});

// Автообновление списка файлов каждые 30 секунд
setInterval(() => {
    if (JWT_TOKEN) {
        loadFileList();
    }
}, 30000);

// Экспорт функций для глобального использования (если нужно)
window.downloadFile = downloadFile;
window.copyToClipboard = copyToClipboard;