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
function logout() {
    if (confirm('Вы уверены, что хотите выйти?')) {
        localStorage.removeItem('token');
        JWT_TOKEN = null;
        
        const loginForm = document.getElementById('loginForm');
        const mainApp = document.getElementById('mainApp');
        const fileList = document.getElementById('fileList');
        
        if (loginForm) loginForm.style.display = 'block';
        if (mainApp) mainApp.style.display = 'none';
        if (fileList) fileList.innerHTML = '';
        
        alert('Вы успешно вышли из системы');
    }
}

async function handleLogin(event) {
    event.preventDefault();

    const username = document.getElementById('username').value.trim();
    const password = document.getElementById('password').value;

    if (!username || !password) {
        alert('Введите логин и пароль');
        return;
    }

    try {
        const response = await fetch(`${API_BASE}/auth/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: new URLSearchParams({ username, password })
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || 'Ошибка входа');
        }

        const data = await response.json();
        JWT_TOKEN = data.access_token;
        localStorage.setItem('token', JWT_TOKEN);

        alert(`Добро пожаловать, ${data.username}!`);

        document.getElementById('loginForm').style.display = 'none';
        document.getElementById('mainApp').style.display = 'block';
        loadFileList();

    } catch (error) {
        alert(`Ошибка входа: ${error.message}`);
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