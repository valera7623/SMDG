// static/js/modules/files.js

import { files as filesAPI } from '../core/api.js';
import { showNotification } from '../utils/notifications.js';
import { formatBytes } from '../utils/formats.js';
import { FILE_AUTO_REMOVE_DELAY, FILE_REFRESH_INTERVAL } from '../core/config.js';
import { setVisible } from '../utils/dom.js';

// ── Список файлов ─────────────────────────────────────────────────────────────

export async function loadFileList() {
    const fileList = document.getElementById('fileList');
    if (!fileList) return;

    fileList.innerHTML = '<div class="loading">⏳ Загрузка...</div>';

    try {
        const data = await filesAPI.list();

        if (data.count === 0) {
            fileList.innerHTML = '<div class="empty">📭 Нет загруженных файлов</div>';
            return;
        }

        fileList.innerHTML = '';
        data.files.forEach(file => fileList.appendChild(_createFileItem(file)));

    } catch (error) {
        if (error.status === 401 || error.status === 403) {
            setVisible(document.getElementById('authForm'), true);
            setVisible(document.getElementById('mainApp'), false);
            return;
        }
        fileList.innerHTML = `<div class="error">❌ ${error.message}</div>`;
    }
}

function _createFileItem(file) {
    const encryptedName = file.name;
    const originalName = file.original_name
        ?? encryptedName.replace(/^[a-f0-9]+_/, '').replace(/\.age$/, '');

    // Определяем DICOM-файл
    const isDicom = file.mime_type === 'application/dicom'
        || file.original_name?.match(/\.(dcm|dicom)$/i);

    const item = document.createElement('div');
    item.className = 'file-item';

    const infoDiv = document.createElement('div');
    infoDiv.className = 'file-info';
    const fileIcon = isDicom ? '🔬' : '📄';
    infoDiv.innerHTML = `
        <div class="file-name">${fileIcon} ${originalName}</div>
        <div class="file-size">📏 ${formatBytes(file.size)}</div>
        ${file.patient_id ? `<div class="patient-id">🆔 Пациент: ${file.patient_id}</div>` : ''}
        <div class="file-id">🔐 <small>${encryptedName}</small></div>
    `;

    const actionsDiv = document.createElement('div');
    actionsDiv.className = 'file-actions';

    // Кнопка «Просмотр» для DICOM-файлов (если viewer включён)
    if (isDicom && window.__DICOM_VIEWER_ENABLED__) {
        const btnView = document.createElement('button');
        btnView.className = 'btn-info btn-small dicom-view-btn';
        btnView.textContent = '👁️ Просмотр';
        btnView.addEventListener('click', () => openDicomViewer(file.id, originalName));
        actionsDiv.appendChild(btnView);
    }

    if (file.download_url) {
        const link = document.createElement('a');
        link.href = file.download_url;
        link.target = '_blank';
        link.className = 'btn-secondary btn-small';
        link.textContent = '📥 Скачать';
        actionsDiv.appendChild(link);
    } else {
        const btnDl = document.createElement('button');
        btnDl.className = 'btn-secondary btn-small';
        btnDl.textContent = '📥 Скачать';
        btnDl.addEventListener('click', () => downloadFile(encryptedName));
        actionsDiv.appendChild(btnDl);
    }

    const btnDel = document.createElement('button');
    btnDel.className = 'btn-danger btn-small';
    btnDel.textContent = '🗑️ Удалить';
    btnDel.addEventListener('click', () => deleteUserFile(encryptedName, originalName));
    actionsDiv.appendChild(btnDel);

    item.appendChild(infoDiv);
    item.appendChild(actionsDiv);
    return item;
}

// ── Загрузка файла ────────────────────────────────────────────────────────────

export async function handleFileUpload(event) {
    event.preventDefault();

    const form = event.target;
    const fileInput = form.querySelector('input[type="file"]');
    const submitBtn = form.querySelector('button[type="submit"]');

    if (!fileInput?.files.length) {
        showNotification('Выберите файл', 'error');
        return;
    }

    const originalText = submitBtn.textContent;
    submitBtn.textContent = '⏳ Шифрование...';
    submitBtn.disabled = true;

    try {
        const data = await filesAPI.upload(fileInput.files[0]);
        
        // ОТЛАДКА: выводим ответ сервера в консоль
        console.log('Upload response:', data);
        console.log('Has download_url:', !!data.download_url);
        console.log('download_url value:', data.download_url);

        // Проверяем разные возможные варианты поля
        const downloadUrl = data.download_url || data.downloadUrl || data.url;
        
        if (downloadUrl) {
            // Добавляем download_url в объект, если его там не было
            if (!data.download_url && downloadUrl) {
                data.download_url = downloadUrl;
            }
            showUploadResult(data);
        } else {
            // Если нет ссылки, но загрузка успешна - просто показываем уведомление
            showNotification(`✅ Файл «${data.original_name || 'файл'}» загружен!`, 'success');
        }

        await loadFileList();
        fileInput.value = '';

        // Очищаем предыдущий результат при успешной загрузке
        const resultDiv = document.getElementById('uploadResult');
        if (resultDiv && !downloadUrl) {
            // Если ссылки нет, но есть ID - можно показать альтернативную информацию
            if (data.id || data.file_id) {
                resultDiv.innerHTML = `
                    <div class="download-link">
                        <p><strong>✅ Файл загружен!</strong></p>
                        <p>ID: ${data.id || data.file_id}</p>
                        <p><small>Ссылка для скачивания будет доступна в списке файлов</small></p>
                    </div>
                `;
                setTimeout(() => {
                    if (resultDiv.firstChild) resultDiv.innerHTML = '';
                }, FILE_AUTO_REMOVE_DELAY);
            }
        }

    } catch (error) {
        console.error('Upload error:', error);
        showNotification(`Ошибка загрузки: ${error.message}`, 'error');
    } finally {
        submitBtn.textContent = originalText;
        submitBtn.disabled = false;
    }
}

// ── Скачивание ────────────────────────────────────────────────────────────────

export async function downloadFile(encryptedFilename) {
    try {
        const response = await filesAPI.download(encryptedFilename);
        const blob = await response.blob();
        const name = encryptedFilename.replace(/^[a-f0-9]+_/, '').replace(/\.age$/, '');

        _triggerDownload(blob, name);
    } catch (error) {
        showNotification(`Ошибка скачивания: ${error.message}`, 'error');
    }
}

function _triggerDownload(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.style.display = 'none';
    document.body.appendChild(a);
    a.click();
    setTimeout(() => {
        URL.revokeObjectURL(url);
        document.body.removeChild(a);
    }, 100);
}

// ── Удаление ──────────────────────────────────────────────────────────────────

export async function deleteUserFile(filename, originalName) {
    if (!confirm(`Удалить файл «${originalName || filename}»?`)) return;

    try {
        const result = await filesAPI.deleteUserFile(filename);
        showNotification(result.message || 'Файл удалён', 'success');
        await loadFileList();
    } catch (error) {
        showNotification(`Ошибка: ${error.message}`, 'error');
    }
}

// ── Блок результата загрузки ──────────────────────────────────────────────────

export function showUploadResult(data) {
    const resultDiv = document.getElementById('uploadResult');
    if (!resultDiv) {
        console.error('Element #uploadResult not found in DOM');
        return;
    }

    console.log('showUploadResult called with:', data);

    const downloadUrl = data.download_url || data.downloadUrl || data.url;
    
    if (!downloadUrl) {
        console.warn('No download URL in response:', data);
        showNotification('Файл загружен, но ссылка не получена', 'warning');
        return;
    }

    const expiresDate = data.expires_at
        ? new Date(data.expires_at).toLocaleString('ru-RU')
        : 'Не указано';

    // Очищаем предыдущий результат
    resultDiv.innerHTML = '';

    const container = document.createElement('div');
    container.className = 'download-link';
    container.style.cssText = `
        background: #f0f9ff;
        border: 1px solid #bae6fd;
        border-radius: 8px;
        padding: 15px;
        margin-top: 15px;
        animation: slideIn 0.3s ease;
    `;

    // Заголовок
    const title = document.createElement('p');
    title.innerHTML = `<strong>✅ Файл «${escapeHtml(data.original_name || 'файл')}» загружен!</strong>`;
    container.appendChild(title);

    // Подпись для ссылки
    const linkLabel = document.createElement('p');
    linkLabel.innerHTML = '<strong>Ссылка для скачивания:</strong>';
    container.appendChild(linkLabel);

    // Поле ввода со ссылкой
    const linkInput = document.createElement('input');
    linkInput.type = 'text';
    linkInput.value = downloadUrl;
    linkInput.readOnly = true;
    linkInput.style.cssText = 'width: 100%; padding: 8px; margin-bottom: 10px; border: 1px solid #ccc; border-radius: 4px;';
    container.appendChild(linkInput);

    // Кнопка копирования
    const copyBtn = document.createElement('button');
    copyBtn.textContent = '📋 Копировать ссылку';
    copyBtn.className = 'btn-secondary';
    copyBtn.style.marginBottom = '10px';
    copyBtn.addEventListener('click', () => {
        linkInput.select();
        document.execCommand('copy');
        showNotification('Ссылка скопирована!', 'success');
    });
    container.appendChild(copyBtn);

    // Дополнительная информация
    const info = document.createElement('p');
    info.innerHTML = `<small>⏰ Срок действия: ${expiresDate} | 🔢 Макс. загрузок: ${data.max_downloads ?? 'Не ограничено'}</small>`;
    info.style.marginTop = '10px';
    info.style.color = '#666';
    container.appendChild(info);

    resultDiv.appendChild(container);

    // Автоудаление через указанное время
    setTimeout(() => {
        if (container.parentNode) {
            container.style.animation = 'slideOut 0.3s ease';
            setTimeout(() => {
                if (container.parentNode) container.remove();
            }, 300);
        }
    }, FILE_AUTO_REMOVE_DELAY);
}

// Вспомогательная функция для escapeHtml (если нет в dom.js)
function escapeHtml(unsafe) {
    if (typeof unsafe !== 'string') return '';
    return unsafe
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

export function copyToClipboard(inputEl) {
    if (inputEl.select) {
        inputEl.select();
        document.execCommand('copy');
        showNotification('Ссылка скопирована!', 'success');
    }
}

// ── DICOM Viewer ─────────────────────────────────────────────────────────────

/**
 * Открывает DICOM viewer в модальном окне с iframe.
 * Запрашивает у бэкенда view-токен и встраивает viewer через iframe.
 */
export async function openDicomViewer(fileId, fileName) {
    try {
        const response = await fetch(`/api/dicom/view-url?file_id=${fileId}`, {
            method: 'POST',
            credentials: 'include',
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || `HTTP ${response.status}`);
        }

        const data = await response.json();
        _showDicomViewerModal(data.view_url, data.file_name || fileName, data.expires_at);
    } catch (error) {
        showNotification(`Ошибка открытия viewer: ${error.message}`, 'error');
    }
}

/**
 * Показывает модальное окно с iframe для DICOM viewer.
 */
function _showDicomViewerModal(iframeUrl, fileName, expiresAt) {
    // Проверяем, нет ли уже открытого viewer
    const existing = document.getElementById('dicomViewerModal');
    if (existing) existing.remove();

    const expiresLabel = expiresAt
        ? new Date(expiresAt).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
        : '—';

    const modal = document.createElement('div');
    modal.id = 'dicomViewerModal';
    modal.className = 'dicom-modal';
    modal.innerHTML = `
        <div class="dicom-modal-header">
            <div class="dicom-modal-title">
                <span class="dicom-modal-icon">🔬</span>
                <span class="dicom-modal-filename">${escapeHtml(fileName)}</span>
                <span class="dicom-modal-expires" title="Сессия истекает в ${expiresLabel}">⏰ ${expiresLabel}</span>
            </div>
            <div class="dicom-modal-actions">
                <button class="dicom-modal-btn dicom-modal-btn-close" id="dicomModalClose" title="Закрыть">
                    ✕ Закрыть
                </button>
            </div>
        </div>
        <div class="dicom-modal-body">
            <div class="dicom-modal-loading" id="dicomModalLoading">
                <div class="dicom-modal-spinner"></div>
                <p>Загрузка DICOM viewer...</p>
            </div>
            <iframe
                id="dicomModalIframe"
                src="${iframeUrl}"
                class="dicom-modal-iframe"
                allow="fullscreen"
                referrerpolicy="no-referrer"
                style="opacity: 0;"
            ></iframe>
        </div>
    `;

    document.body.appendChild(modal);
    document.body.style.overflow = 'hidden';

    // Закрытие
    const closeBtn = modal.querySelector('#dicomModalClose');
    closeBtn.addEventListener('click', () => _closeDicomViewerModal());

    // Закрытие по Escape
    const onKeydown = (e) => {
        if (e.key === 'Escape') {
            _closeDicomViewerModal();
            document.removeEventListener('keydown', onKeydown);
        }
    };
    document.addEventListener('keydown', onKeydown);

    // Закрытие по клику на overlay
    modal.addEventListener('click', (e) => {
        if (e.target === modal) _closeDicomViewerModal();
    });

    // Когда iframe загрузится — убираем loader
    const iframe = modal.querySelector('#dicomModalIframe');
    const loading = modal.querySelector('#dicomModalLoading');
    iframe.addEventListener('load', () => {
        iframe.style.opacity = '1';
        loading.style.display = 'none';
    });

    // Таймаут на случай если iframe не загрузился
    setTimeout(() => {
        if (loading.style.display !== 'none') {
            loading.innerHTML = '<p class="dicom-modal-error">Viewer не загрузился. <a href="#" onclick="location.reload()">Обновить</a></p>';
        }
    }, 15000);
}

function _closeDicomViewerModal() {
    const modal = document.getElementById('dicomViewerModal');
    if (modal) {
        modal.remove();
        document.body.style.overflow = '';
    }
}

// ── Инициализация ─────────────────────────────────────────────────────────────

export function initFiles() {
    const uploadForm = document.getElementById('uploadForm');
    if (uploadForm) {
        uploadForm.addEventListener('submit', handleFileUpload);
        console.log('Upload form initialized');
    } else {
        console.warn('Upload form not found');
    }

    const refreshBtn = document.getElementById('refreshBtn');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', loadFileList);
        console.log('Refresh button initialized');
    }

    // Автообновление каждые N секунд
    setInterval(loadFileList, FILE_REFRESH_INTERVAL);
}
