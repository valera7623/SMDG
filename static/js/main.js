// static/js/main.js
const API_BASE = '/api';

let JWT_TOKEN = localStorage.getItem('token') || null;

function getAuthHeaders() {
    if (JWT_TOKEN) {
        return { 'Authorization': `Bearer ${JWT_TOKEN}` };
    }
    return {};
}

// Выход из системы
function logout() {
    if (confirm('Вы уверены, что хотите выйти?')) {
        localStorage.removeItem("token");
        JWT_TOKEN = null;

        document.getElementById('mainApp').style.display = 'none';
        document.getElementById('loginForm').style.display = 'block';

        // Очищаем список файлов
        const fileList = document.getElementById('fileList');
        if (fileList) {
            fileList.innerHTML = '';
        }

        alert('Вы успешно вышли из системы');
    }
}

document.addEventListener('DOMContentLoaded', function () {
    if (JWT_TOKEN) {
        document.getElementById('loginForm').style.display = 'none';
        document.getElementById('mainApp').style.display = 'block';
        loadFileList();
    } else {
        document.getElementById('loginForm').style.display = 'block';
        document.getElementById('mainApp').style.display = 'none';
    }

    setupForms();
});

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
        localStorage.setItem("token", JWT_TOKEN);

        alert(`Добро пожаловать, ${data.username}!`);

        document.getElementById('loginForm').style.display = 'none';
        document.getElementById('mainApp').style.display = 'block';
        loadFileList();

    } catch (error) {
        alert(`Ошибка входа: ${error.message}`);
    }
}

// Обработчик формы загрузки (обновлённый)
// Обработчик формы загрузки файла
document.getElementById('uploadForm')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const fileInput = document.getElementById('fileInput');
    const file = fileInput.files[0];
    if (!file) {
        alert('❌ Выберите файл');
        return;
    }

    const formData = new FormData();
    formData.append('file', file);

    try {
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

        // Показываем блок со ссылкой
        if (data.download_url) {
            showDownloadLink(data.download_url, data.original_name, data.expires_at, data.max_downloads);
        } else {
            alert('✅ Файл загружен, но ссылка не получена');
        }

        // Обновляем список файлов
        loadFileList();

        // Очищаем инпут
        fileInput.value = '';
    } catch (error) {
        alert(`❌ ${error.message}`);
    }
});

// Функция показа блока со ссылкой
function showDownloadLink(url, filename, expiresAt, maxDownloads) {
    const resultDiv = document.getElementById('uploadResult');
    if (!resultDiv) {
        console.warn('Элемент #uploadResult не найден');
        return;  // Если див не найден, не показываем
    }

    // Очищаем предыдущий контент
    resultDiv.innerHTML = '';

    // Форматируем дату
    const expiresDate = expiresAt ? new Date(expiresAt).toLocaleString('ru-RU') : 'Не указано';

    // Создаём блок
    const linkContainer = document.createElement('div');
    linkContainer.className = 'download-link';
    linkContainer.innerHTML = `
        <p><strong>✅ Файл "${filename}" загружен!</strong></p>
        <p><strong>Ссылка для скачивания:</strong></p>
        <input type="text" value="${url}" readonly style="width: 100%; padding: 8px; margin-bottom: 10px;">
        <button onclick="copyToClipboard(this.previousElementSibling)">Копировать</button>
        <p><small>Срок действия: ${expiresDate} | Макс. скачиваний: ${maxDownloads}</small></p>
    `;

    resultDiv.appendChild(linkContainer);

    // Автоисчезновение через 30 сек
    setTimeout(() => {
        linkContainer.remove();
    }, 30000);
}

// Функция копирования в буфер
function copyToClipboard(input) {
    input.select();
    document.execCommand('copy');
    alert('✅ Ссылка скопирована!');
}

async function loadFileList() {
    const fileList = document.getElementById('fileList');
    if (!fileList) return;

    fileList.innerHTML = '<div class="loading">⏳ Загрузка...</div>';

    try {
        const response = await fetch(`${API_BASE}/list`, { headers: getAuthHeaders() });

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
            // file.name — это полное зашифрованное имя (с префиксом и .age) — именно его нужно для скачивания
            const encryptedName = file.name;
            const originalName = file.original_name || encryptedName.replace(/^[a-f0-9]+_/, '').replace('.age$', '');

            html += `
                <div class="file-item">
                    <div class="file-info">
                        <div class="file-name">📄 ${originalName}</div>
                        <div class="file-size">
                            📏 ${file.size} байт<br>
                            🔐 <small>${encryptedName}</small>
                        </div>
                    </div>
                    <button onclick="downloadFile('${encryptedName}')" class="btn-secondary">📥 Скачать</button>
                </div>
            `;
        });

        fileList.innerHTML = html;

    } catch (error) {
        fileList.innerHTML = `<div class="error">❌ ${error.message}</div>`;
    }
}

async function handleUpload(event) {
    event.preventDefault();

    const form = event.target;
    const fileInput = form.querySelector('input[name="file"]');
    const btn = form.querySelector('button[type="submit"]');

    if (!fileInput.files.length) {
        alert('Выберите файл');
        return;
    }

    const oldText = btn.textContent;
    btn.textContent = '⏳ Шифрование...';
    btn.disabled = true;

    try {
        const formData = new FormData(form);

        const response = await fetch(`${API_BASE}/upload`, {
            method: 'POST',
            body: formData,
            headers: getAuthHeaders()
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || `Ошибка ${response.status}`);
        }

        const result = await response.json();
        alert(`✅ Успешно загружен: ${result.encrypted_file}`);
        fileInput.value = '';
        loadFileList();

    } catch (error) {
        alert(`❌ Ошибка загрузки: ${error.message}`);
    } finally {
        btn.textContent = oldText;
        btn.disabled = false;
    }
}

async function downloadFile(encryptedFilename) {
    try {
        const response = await fetch(`${API_BASE}/download?filename=${encodeURIComponent(encryptedFilename)}`, {
            headers: getAuthHeaders()
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || `Ошибка ${response.status}`);
        }

        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = encryptedFilename.replace(/^[a-f0-9]+_/, '').replace('.age$', '');  // оригинальное имя
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        a.remove();

    } catch (error) {
        alert(`❌ Ошибка скачивания: ${error.message}`);
    }
}

async function handleDownload(event) {
    event.preventDefault();
    const input = document.querySelector('#downloadForm input[name="filename"]');
    const filename = input.value.trim();
    if (filename) {
        await downloadFile(filename);
        input.value = '';
    } else {
        alert('Введите имя зашифрованного файла (с .age)');
    }
}

// static/js/main.js
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

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || 'Ошибка смены пароля');
        }

        alert('✅ Пароль успешно изменён');
    } catch (error) {
        alert(`❌ ${error.message}`);
    }
}

// Пример вызова из формы
document.getElementById('changePassForm')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const oldPass = document.getElementById('oldPassword').value;
    const newPass = document.getElementById('newPassword').value;
    await changePassword(oldPass, newPass);
});

setInterval(() => {
    if (JWT_TOKEN) loadFileList();
}, 30000);
