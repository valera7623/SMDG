// static/js/main.js
const API_BASE = '/api';
let JWT_TOKEN = localStorage.getItem('token') || null;

// Утилиты
function getAuthHeaders(contentType = null) {
    const headers = {};
    
    if (JWT_TOKEN) {
        headers['Authorization'] = `Bearer ${JWT_TOKEN}`;
    }
    
    if (contentType) {
        headers['Content-Type'] = contentType;
    }
    
    return headers;
}

function showNotification(message, type = 'info') {
    // Создаем уведомление вместо alert
    const notification = document.createElement('div');
    notification.className = `notification ${type}`;
    notification.innerHTML = `
        <i class="fas fa-${type === 'success' ? 'check-circle' : 
                         type === 'error' ? 'exclamation-circle' : 
                         'info-circle'}"></i>
        <span>${message}</span>
    `;
    
    document.body.appendChild(notification);
    
    // Автоудаление через 3 секунды
    setTimeout(() => {
        notification.classList.add('fade-out');
        setTimeout(() => notification.remove(), 300);
    }, 3000);
}

function formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

// Выход из системы
function logout() {
    if (confirm('Вы уверены, что хотите выйти?')) {
        localStorage.removeItem("token");
        JWT_TOKEN = null;
        
        document.getElementById('loginForm').style.display = 'block';
        document.getElementById('mainApp').style.display = 'none';
        
        // Очищаем поля формы
        document.getElementById('username').value = '';
        document.getElementById('password').value = '';
        
        // Очищаем список файлов
        const fileList = document.getElementById('fileList');
        if (fileList) {
            fileList.innerHTML = '<div class="empty">📭 Нет загруженных файлов</div>';
        }
        
        showNotification('Вы успешно вышли из системы', 'success');
    }
}

// Инициализация при загрузке страницы
document.addEventListener('DOMContentLoaded', function () {
    console.log('DOM loaded, token:', JWT_TOKEN ? 'present' : 'none');
    
    const loginForm = document.getElementById('loginForm');
    const mainApp = document.getElementById('mainApp');
    
    if (JWT_TOKEN) {
        // Проверяем токен на валидность
        verifyToken().then(isValid => {
            if (isValid) {
                loginForm.style.display = 'none';
                mainApp.style.display = 'block';
                loadFileList();
                setupForms();
            } else {
                // Токен невалидный
                JWT_TOKEN = null;
                localStorage.removeItem('token');
                loginForm.style.display = 'block';
                mainApp.style.display = 'none';
            }
        });
    } else {
        loginForm.style.display = 'block';
        mainApp.style.display = 'none';
    }
    
    // Автообновление списка файлов каждые 30 секунд
    setInterval(() => {
        if (JWT_TOKEN && mainApp.style.display !== 'none') {
            loadFileList();
        }
    }, 30000);
});

// Проверка валидности токена
async function verifyToken() {
    try {
        const response = await fetch(`${API_BASE}/auth/verify`, {
            method: 'GET',
            headers: getAuthHeaders()
        });
        return response.ok;
    } catch (error) {
        return false;
    }
}

// Обработчик входа
async function handleLogin(event) {
    event.preventDefault();

    const username = document.getElementById('username').value.trim();
    const password = document.getElementById('password').value;
    const loginButton = event.target.querySelector('button[type="submit"]');
    const originalText = loginButton.innerHTML;

    if (!username || !password) {
        showNotification('Введите логин и пароль', 'error');
        return;
    }

    try {
        // Показываем состояние загрузки
        loginButton.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Вход...';
        loginButton.disabled = true;

        const response = await fetch(`${API_BASE}/auth/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: new URLSearchParams({ username, password })
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.detail || data.message || `Ошибка ${response.status}`);
        }

        // Сохраняем токен
        JWT_TOKEN = data.access_token;
        localStorage.setItem("token", JWT_TOKEN);

        showNotification(`Добро пожаловать, ${data.username || username}!`, 'success');

        // Переключаем интерфейс
        document.getElementById('loginForm').style.display = 'none';
        document.getElementById('mainApp').style.display = 'block';
        
        // Загружаем данные
        loadFileList();
        setupForms();
        
        // Очищаем поля формы
        document.getElementById('username').value = '';
        document.getElementById('password').value = '';

    } catch (error) {
        console.error('Login error:', error);
        showNotification(`Ошибка входа: ${error.message}`, 'error');
    } finally {
        // Восстанавливаем кнопку
        loginButton.innerHTML = originalText;
        loginButton.disabled = false;
    }
}

// Настройка форм
function setupForms() {
    const uploadForm = document.getElementById('uploadForm');
    if (uploadForm) {
        uploadForm.removeEventListener('submit', handleUpload);
        uploadForm.addEventListener('submit', handleUpload);
    }

    const downloadForm = document.getElementById('downloadForm');
    if (downloadForm) {
        downloadForm.removeEventListener('submit', handleDownload);
        downloadForm.addEventListener('submit', handleDownload);
    }
}

// Загрузка списка файлов
async function loadFileList() {
    const fileList = document.getElementById('fileList');
    if (!fileList) return;

    const loadingHtml = `
        <div class="loading">
            <i class="fas fa-spinner fa-spin"></i> Загрузка списка файлов...
        </div>
    `;
    
    // Сохраняем текущую позицию скролла
    const scrollPos = fileList.scrollTop;
    fileList.innerHTML = loadingHtml;

    try {
        const response = await fetch(`${API_BASE}/list`, { 
            headers: getAuthHeaders() 
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || `Ошибка ${response.status}`);
        }

        const data = await response.json();

        if (!data.files || data.files.length === 0) {
            fileList.innerHTML = '<div class="empty">📭 Нет загруженных файлов</div>';
            return;
        }

        let html = '';
        data.files.forEach(file => {
            const encryptedName = file.name;
            const originalName = file.original_name || encryptedName.replace(/^[a-f0-9]+_/, '').replace('.age$', '');
            const fileSize = file.size ? formatFileSize(file.size) : 'Неизвестно';
            const uploadDate = file.created ? new Date(file.created).toLocaleString() : 'Неизвестно';

            html += `
                <div class="file-item">
                    <div class="file-info">
                        <div class="file-name">
                            <i class="fas fa-file"></i> ${originalName}
                        </div>
                        <div class="file-meta">
                            <span class="file-size"><i class="fas fa-hdd"></i> ${fileSize}</span>
                            <span class="file-date"><i class="fas fa-calendar"></i> ${uploadDate}</span>
                            <span class="file-encrypted"><i class="fas fa-lock"></i> ${encryptedName}</span>
                        </div>
                    </div>
                    <button onclick="downloadFile('${encryptedName}')" class="btn-secondary">
                        <i class="fas fa-download"></i> Скачать
                    </button>
                </div>
            `;
        });

        fileList.innerHTML = html;
        
        // Восстанавливаем позицию скролла
        fileList.scrollTop = scrollPos;

    } catch (error) {
        console.error('Error loading file list:', error);
        fileList.innerHTML = `
            <div class="error">
                <i class="fas fa-exclamation-triangle"></i> ${error.message}
            </div>
        `;
    }
}

// Загрузка файла
async function handleUpload(event) {
    event.preventDefault();

    const form = event.target;
    const fileInput = form.querySelector('input[name="file"]');
    const btn = form.querySelector('button[type="submit"]');

    if (!fileInput.files.length) {
        showNotification('Выберите файл для загрузки', 'error');
        return;
    }

    const file = fileInput.files[0];
    if (file.size > 100 * 1024 * 1024) { // 100MB лимит
        showNotification('Файл слишком большой (макс. 100MB)', 'error');
        return;
    }

    const oldText = btn.innerHTML;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Шифрование...';
    btn.disabled = true;

    try {
        const formData = new FormData(form);

        const response = await fetch(`${API_BASE}/upload`, {
            method: 'POST',
            body: formData,
            headers: getAuthHeaders()
        });

        const result = await response.json();

        if (!response.ok) {
            throw new Error(result.detail || result.message || `Ошибка ${response.status}`);
        }

        showNotification(`✅ Файл успешно загружен: ${result.encrypted_file}`, 'success');
        fileInput.value = '';
        loadFileList();

    } catch (error) {
        console.error('Upload error:', error);
        showNotification(`❌ Ошибка загрузки: ${error.message}`, 'error');
    } finally {
        btn.innerHTML = oldText;
        btn.disabled = false;
    }
}

// Скачивание файла по имени
async function downloadFile(encryptedFilename) {
    try {
        const downloadBtn = event?.target || document.querySelector(`button[onclick*="${encryptedFilename}"]`);
        if (downloadBtn) {
            const originalText = downloadBtn.innerHTML;
            downloadBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
            downloadBtn.disabled = true;
        }

        const response = await fetch(`${API_BASE}/download?filename=${encodeURIComponent(encryptedFilename)}`, {
            headers: getAuthHeaders()
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || `Ошибка ${response.status}`);
        }

        // Получаем имя файла из заголовков или генерируем
        const contentDisposition = response.headers.get('Content-Disposition');
        let filename = encryptedFilename.replace(/^[a-f0-9]+_/, '').replace('.age$', '');
        
        if (contentDisposition) {
            const match = contentDisposition.match(/filename="?([^"]+)"?/);
            if (match) filename = match[1];
        }

        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        
        // Очистка
        setTimeout(() => {
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);
        }, 100);

        showNotification(`✅ Файл "${filename}" скачан`, 'success');

    } catch (error) {
        console.error('Download error:', error);
        showNotification(`❌ Ошибка скачивания: ${error.message}`, 'error');
    } finally {
        // Восстанавливаем кнопку
        const downloadBtn = event?.target || document.querySelector(`button[onclick*="${encryptedFilename}"]`);
        if (downloadBtn) {
            downloadBtn.innerHTML = '<i class="fas fa-download"></i> Скачать';
            downloadBtn.disabled = false;
        }
    }
}

// Скачивание через форму
async function handleDownload(event) {
    event.preventDefault();
    
    const input = document.querySelector('#downloadForm input[name="filename"]');
    const btn = event.target.querySelector('button[type="submit"]');
    const filename = input.value.trim();
    
    if (!filename) {
        showNotification('Введите имя зашифрованного файла', 'error');
        return;
    }

    const oldText = btn.innerHTML;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
    btn.disabled = true;

    try {
        await downloadFile(filename);
        input.value = '';
    } catch (error) {
        // Ошибка уже обработана в downloadFile
    } finally {
        btn.innerHTML = oldText;
        btn.disabled = false;
    }
}

// Смена пароля
async function changePassword(oldPass, newPass) {
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

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.detail || data.message || 'Ошибка смены пароля');
        }

        showNotification('✅ Пароль успешно изменён', 'success');
        return true;
        
    } catch (error) {
        console.error('Password change error:', error);
        showNotification(`❌ ${error.message}`, 'error');
        return false;
    }
}

// Добавляем CSS для уведомлений
if (!document.querySelector('#notification-styles')) {
    const style = document.createElement('style');
    style.id = 'notification-styles';
    style.textContent = `
        .notification {
            position: fixed;
            top: 20px;
            right: 20px;
            padding: 15px 20px;
            border-radius: 8px;
            color: white;
            font-weight: bold;
            display: flex;
            align-items: center;
            gap: 10px;
            z-index: 1000;
            animation: slideIn 0.3s ease;
            max-width: 400px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        }
        
        .notification.success {
            background: linear-gradient(135deg, #28a745, #218838);
            border-left: 4px solid #1e7e34;
        }
        
        .notification.error {
            background: linear-gradient(135deg, #dc3545, #c82333);
            border-left: 4px solid #bd2130;
        }
        
        .notification.info {
            background: linear-gradient(135deg, #17a2b8, #138496);
            border-left: 4px solid #117a8b;
        }
        
        .notification.fade-out {
            animation: fadeOut 0.3s ease forwards;
        }
        
        @keyframes slideIn {
            from {
                transform: translateX(100%);
                opacity: 0;
            }
            to {
                transform: translateX(0);
                opacity: 1;
            }
        }
        
        @keyframes fadeOut {
            from {
                transform: translateX(0);
                opacity: 1;
            }
            to {
                transform: translateX(100%);
                opacity: 0;
            }
        }
        
        .loading, .empty, .error {
            text-align: center;
            padding: 30px;
            color: #666;
            font-style: italic;
        }
        
        .error {
            color: #dc3545;
            background: #f8d7da;
            border-radius: 8px;
            padding: 20px;
        }
        
        .file-meta {
            margin-top: 5px;
            font-size: 0.85em;
            color: #666;
            display: flex;
            flex-wrap: wrap;
            gap: 15px;
        }
        
        .file-meta span {
            display: inline-flex;
            align-items: center;
            gap: 5px;
        }
    `;
    document.head.appendChild(style);
}

// Экспорт функций для использования в консоли
window.handleLogin = handleLogin;
window.logout = logout;
window.loadFileList = loadFileList;
window.downloadFile = downloadFile;
window.handleUpload = handleUpload;
window.handleDownload = handleDownload;
window.changePassword = changePassword;