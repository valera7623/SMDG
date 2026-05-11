// static/js/modules/files.js

import { files as filesAPI } from '../core/api.js';
import { showNotification } from '../utils/notifications.js';
import { formatBytes } from '../utils/formats.js';
import { FILE_AUTO_REMOVE_DELAY, FILE_REFRESH_INTERVAL } from '../core/config.js';
import { setVisible } from '../utils/dom.js';
import { t, currentLocale } from '../utils/i18n.js';

// ── File list ────────────────────────────────────────────────────────────────

export async function loadFileList() {
    const fileList = document.getElementById('fileList');
    if (!fileList) return;

    fileList.innerHTML = `<div class="loading">⏳ ${t('common.loading', 'Loading…')}</div>`;

    try {
        const data = await filesAPI.list();

        if (data.count === 0) {
            fileList.innerHTML = `<div class="empty">📭 ${t('files.list_empty', 'No uploaded files')}</div>`;
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

    const isDicom = file.mime_type === 'application/dicom'
        || file.original_name?.match(/\.(dcm|dicom)$/i);

    const item = document.createElement('div');
    item.className = 'file-item';

    const infoDiv = document.createElement('div');
    infoDiv.className = 'file-info';
    const fileIcon = isDicom ? '🔬' : '📄';
    const nameDiv = document.createElement('div');
    nameDiv.className = 'file-name';
    nameDiv.textContent = `${fileIcon} ${originalName}`;
    infoDiv.appendChild(nameDiv);

    const sizeDiv = document.createElement('div');
    sizeDiv.className = 'file-size';
    sizeDiv.textContent = `📏 ${formatBytes(file.size)}`;
    infoDiv.appendChild(sizeDiv);

    if (file.patient_id) {
        const patientDiv = document.createElement('div');
        patientDiv.className = 'patient-id';
        patientDiv.textContent = `🆔 ${t('files.patient_label', 'Patient: {{id}}', { id: file.patient_id })}`;
        infoDiv.appendChild(patientDiv);
    }

    const idDiv = document.createElement('div');
    idDiv.className = 'file-id';
    idDiv.appendChild(document.createTextNode('🔐 '));
    const small = document.createElement('small');
    small.textContent = encryptedName;
    idDiv.appendChild(small);
    infoDiv.appendChild(idDiv);

    const actionsDiv = document.createElement('div');
    actionsDiv.className = 'file-actions';

    if (isDicom && window.__DICOM_VIEWER_ENABLED__) {
        const btnView = document.createElement('button');
        btnView.className = 'btn-info btn-small dicom-view-btn';
        btnView.textContent = `👁️ ${t('files.btn_view', 'View')}`;
        btnView.title = t('files.btn_view_title', 'Open embedded DICOM Viewer');
        btnView.addEventListener('click', () => openDicomViewer(file.id, originalName));
        actionsDiv.appendChild(btnView);

        const btnOHIF = document.createElement('button');
        btnOHIF.className = 'btn-info btn-small dicom-view-btn';
        btnOHIF.textContent = `🏥 ${t('files.btn_ohif', 'OHIF')}`;
        btnOHIF.title = t('files.btn_ohif_title', 'Open OHIF Viewer (DICOMweb)');
        btnOHIF.addEventListener('click', () => openOHIFViewer(file.id, originalName));
        actionsDiv.appendChild(btnOHIF);
    }

    if (file.download_url) {
        const link = document.createElement('a');
        link.href = file.download_url;
        link.target = '_blank';
        link.className = 'btn-secondary btn-small';
        link.textContent = `📥 ${t('files.btn_download', 'Download')}`;
        actionsDiv.appendChild(link);
    } else {
        const btnDl = document.createElement('button');
        btnDl.className = 'btn-secondary btn-small';
        btnDl.textContent = `📥 ${t('files.btn_download', 'Download')}`;
        btnDl.addEventListener('click', () => downloadFile(encryptedName));
        actionsDiv.appendChild(btnDl);
    }

    const btnDel = document.createElement('button');
    btnDel.className = 'btn-danger btn-small';
    btnDel.textContent = `🗑️ ${t('files.btn_delete', 'Delete')}`;
    btnDel.addEventListener('click', () => deleteUserFile(encryptedName, originalName));
    actionsDiv.appendChild(btnDel);

    item.appendChild(infoDiv);
    item.appendChild(actionsDiv);
    return item;
}

// ── Upload ───────────────────────────────────────────────────────────────────

export async function handleFileUpload(event) {
    event.preventDefault();

    const form = event.target;
    const fileInput = form.querySelector('input[type="file"]');
    const submitBtn = form.querySelector('button[type="submit"]');
    const nameEl = form.querySelector('#fileInputName');

    if (!fileInput?.files.length) {
        showNotification(t('files.select_file', 'Select a file'), 'error');
        return;
    }

    const originalText = submitBtn.textContent;
    submitBtn.textContent = `⏳ ${t('files.btn_encrypting', 'Encrypting…')}`;
    submitBtn.disabled = true;

    try {
        const data = await filesAPI.upload(fileInput.files[0]);

        console.log('Upload response:', data);

        const downloadUrl = data.download_url || data.downloadUrl || data.url;

        if (downloadUrl) {
            if (!data.download_url && downloadUrl) {
                data.download_url = downloadUrl;
            }
            showUploadResult(data);
        } else {
            const name = data.original_name || t('files.unnamed', 'file');
            showNotification(`✅ ${t('files.uploaded_named', 'File «{{name}}» uploaded!', { name })}`, 'success');
        }

        await loadFileList();
        fileInput.value = '';
        _resetFilePickerName(nameEl);

        const resultDiv = document.getElementById('uploadResult');
        if (resultDiv && !downloadUrl) {
            if (data.id || data.file_id) {
                const id = data.id || data.file_id;
                resultDiv.innerHTML = `
                    <div class="download-link">
                        <p><strong>✅ ${t('files.uploaded_short', 'File uploaded!')}</strong></p>
                        <p>${t('files.uploaded_id', 'ID: {{id}}', { id })}</p>
                        <p><small>${t('files.uploaded_link_in_list', 'The download link will be available in the file list')}</small></p>
                    </div>
                `;
                setTimeout(() => {
                    if (resultDiv.firstChild) resultDiv.innerHTML = '';
                }, FILE_AUTO_REMOVE_DELAY);
            }
        }

    } catch (error) {
        console.error('Upload error:', error);
        showNotification(
            t('files.upload_error', 'Upload error: {{message}}', { message: error.message }),
            'error',
        );
    } finally {
        submitBtn.textContent = originalText;
        submitBtn.disabled = false;
    }
}

// ── Download ─────────────────────────────────────────────────────────────────

export async function downloadFile(encryptedFilename) {
    try {
        const response = await filesAPI.download(encryptedFilename);
        const blob = await response.blob();
        const name = encryptedFilename.replace(/^[a-f0-9]+_/, '').replace(/\.age$/, '');

        _triggerDownload(blob, name);
    } catch (error) {
        showNotification(
            t('files.download_error', 'Download error: {{message}}', { message: error.message }),
            'error',
        );
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

// ── Delete ───────────────────────────────────────────────────────────────────

export async function deleteUserFile(filename, originalName) {
    const name = originalName || filename;
    if (!confirm(t('files.delete_confirm_named', 'Delete file «{{name}}»?', { name }))) return;

    try {
        const result = await filesAPI.deleteUserFile(filename);
        showNotification(result.message || t('files.delete_done', 'File deleted'), 'success');
        await loadFileList();
    } catch (error) {
        showNotification(
            t('files.generic_error', 'Error: {{message}}', { message: error.message }),
            'error',
        );
    }
}

// ── Upload result block ──────────────────────────────────────────────────────

export function showUploadResult(data) {
    const resultDiv = document.getElementById('uploadResult');
    if (!resultDiv) {
        console.error('Element #uploadResult not found in DOM');
        return;
    }

    const downloadUrl = data.download_url || data.downloadUrl || data.url;

    if (!downloadUrl) {
        console.warn('No download URL in response:', data);
        showNotification(t('files.uploaded_no_link', 'File uploaded, but no link was returned'), 'warning');
        return;
    }

    const expiresDate = data.expires_at
        ? new Date(data.expires_at).toLocaleString(currentLocale())
        : t('files.not_specified', 'Not specified');

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

    const displayName = escapeHtml(data.original_name || t('files.unnamed', 'file'));
    const title = document.createElement('p');
    title.innerHTML = `<strong>✅ ${t('files.uploaded_named', 'File «{{name}}» uploaded!', { name: displayName })}</strong>`;
    container.appendChild(title);

    const linkLabel = document.createElement('p');
    linkLabel.innerHTML = `<strong>${t('files.download_link_label', 'Download link:')}</strong>`;
    container.appendChild(linkLabel);

    const linkInput = document.createElement('input');
    linkInput.type = 'text';
    linkInput.value = downloadUrl;
    linkInput.readOnly = true;
    linkInput.style.cssText = 'width: 100%; padding: 8px; margin-bottom: 10px; border: 1px solid #ccc; border-radius: 4px;';
    container.appendChild(linkInput);

    const copyBtn = document.createElement('button');
    copyBtn.textContent = `📋 ${t('files.copy_link', 'Copy link')}`;
    copyBtn.className = 'btn-secondary';
    copyBtn.style.marginBottom = '10px';
    copyBtn.addEventListener('click', () => {
        linkInput.select();
        document.execCommand('copy');
        showNotification(t('files.link_copied', 'Link copied!'), 'success');
    });
    container.appendChild(copyBtn);

    const info = document.createElement('p');
    const maxDownloads = data.max_downloads ?? t('files.unlimited', 'Unlimited');
    info.innerHTML = `<small>⏰ ${t('files.expires_info', 'Expires: {{date}} | Max downloads: {{count}}', {
        date: expiresDate,
        count: maxDownloads,
    })}</small>`;
    info.style.marginTop = '10px';
    info.style.color = '#666';
    container.appendChild(info);

    resultDiv.appendChild(container);

    setTimeout(() => {
        if (container.parentNode) {
            container.style.animation = 'slideOut 0.3s ease';
            setTimeout(() => {
                if (container.parentNode) container.remove();
            }, 300);
        }
    }, FILE_AUTO_REMOVE_DELAY);
}

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
        showNotification(t('files.link_copied', 'Link copied!'), 'success');
    }
}

// ── DICOM Viewer ─────────────────────────────────────────────────────────────

/**
 * Opens the DICOM viewer in a modal iframe. Requests a view token from the
 * backend and embeds the viewer via an iframe.
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
        showNotification(
            t('files.viewer_open_error', 'Failed to open viewer: {{message}}', { message: error.message }),
            'error',
        );
    }
}

/**
 * Opens the OHIF Viewer in a modal iframe (DICOMweb endpoints).
 */
export async function openOHIFViewer(fileId, fileName) {
    try {
        const response = await fetch(`/api/dicom/ohif-url?file_id=${fileId}`, {
            method: 'POST',
            credentials: 'include',
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || `HTTP ${response.status}`);
        }

        const data = await response.json();
        _showOHIFViewerModal(data.ohif_url, data.file_name || fileName, data.expires_at);
    } catch (error) {
        showNotification(
            t('files.ohif_open_error', 'Failed to open OHIF Viewer: {{message}}', { message: error.message }),
            'error',
        );
    }
}

/**
 * Renders the modal holding the DICOM viewer iframe.
 */
function _showDicomViewerModal(iframeUrl, fileName, expiresAt) {
    const existing = document.getElementById('dicomViewerModal');
    if (existing) existing.remove();

    const expiresLabel = expiresAt
        ? new Date(expiresAt).toLocaleTimeString(currentLocale(), { hour: '2-digit', minute: '2-digit' })
        : '—';
    const expiresTitle = t('files.session_expires_at', 'Session expires at {{time}}', { time: expiresLabel });
    const closeLabel = t('files.modal_close', 'Close');

    const modal = document.createElement('div');
    modal.id = 'dicomViewerModal';
    modal.className = 'dicom-modal';
    modal.innerHTML = `
        <div class="dicom-modal-header">
            <div class="dicom-modal-title">
                <span class="dicom-modal-icon">🔬</span>
                <span class="dicom-modal-filename">${escapeHtml(fileName)}</span>
                <span class="dicom-modal-expires" title="${expiresTitle}">⏰ ${expiresLabel}</span>
            </div>
            <div class="dicom-modal-actions">
                <button class="dicom-modal-btn dicom-modal-btn-close" id="dicomModalClose" title="${closeLabel}">
                    ✕ ${closeLabel}
                </button>
            </div>
        </div>
        <div class="dicom-modal-body">
            <div class="dicom-modal-loading" id="dicomModalLoading">
                <div class="dicom-modal-spinner"></div>
                <p>${t('files.viewer_loading', 'Loading DICOM viewer…')}</p>
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

    const closeBtn = modal.querySelector('#dicomModalClose');
    closeBtn.addEventListener('click', () => _closeDicomViewerModal());

    const onKeydown = (e) => {
        if (e.key === 'Escape') {
            _closeDicomViewerModal();
            document.removeEventListener('keydown', onKeydown);
        }
    };
    document.addEventListener('keydown', onKeydown);

    modal.addEventListener('click', (e) => {
        if (e.target === modal) _closeDicomViewerModal();
    });

    const iframe = modal.querySelector('#dicomModalIframe');
    const loading = modal.querySelector('#dicomModalLoading');
    iframe.addEventListener('load', () => {
        iframe.style.opacity = '1';
        loading.style.display = 'none';
    });

    setTimeout(() => {
        if (loading.style.display !== 'none') {
            loading.innerHTML = `<p class="dicom-modal-error">${t('files.viewer_failed', 'Viewer failed to load.')} <a href="#" onclick="location.reload()">${t('files.reload_link', 'Reload')}</a></p>`;
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

/**
 * Renders the modal holding the OHIF Viewer iframe.
 */
function _showOHIFViewerModal(iframeUrl, fileName, expiresAt) {
    const existing = document.getElementById('ohifViewerModal');
    if (existing) existing.remove();

    const expiresLabel = expiresAt
        ? new Date(expiresAt).toLocaleTimeString(currentLocale(), { hour: '2-digit', minute: '2-digit' })
        : '—';
    const expiresTitle = t('files.session_expires_at', 'Session expires at {{time}}', { time: expiresLabel });
    const closeLabel = t('files.modal_close', 'Close');

    const modal = document.createElement('div');
    modal.id = 'ohifViewerModal';
    modal.className = 'dicom-modal';
    modal.innerHTML = `
        <div class="dicom-modal-header">
            <div class="dicom-modal-title">
                <span class="dicom-modal-icon">🏥</span>
                <span class="dicom-modal-filename">${escapeHtml(fileName)}</span>
                <span class="dicom-modal-expires" title="${expiresTitle}">⏰ ${expiresLabel}</span>
            </div>
            <div class="dicom-modal-actions">
                <button class="dicom-modal-btn dicom-modal-btn-close" id="ohifModalClose" title="${closeLabel}">
                    ✕ ${closeLabel}
                </button>
            </div>
        </div>
        <div class="dicom-modal-body">
            <div class="dicom-modal-loading" id="ohifModalLoading">
                <div class="dicom-modal-spinner"></div>
                <p>${t('files.ohif_loading', 'Loading OHIF Viewer…')}</p>
            </div>
            <iframe
                id="ohifModalIframe"
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

    const closeBtn = modal.querySelector('#ohifModalClose');
    closeBtn.addEventListener('click', () => {
        const m = document.getElementById('ohifViewerModal');
        if (m) {
            m.remove();
            document.body.style.overflow = '';
        }
    });

    const iframe = modal.querySelector('#ohifModalIframe');
    iframe.onload = () => {
        iframe.style.opacity = '1';
        const loading = document.getElementById('ohifModalLoading');
        if (loading) loading.style.display = 'none';
    };

    setTimeout(() => {
        const loading = document.getElementById('ohifModalLoading');
        if (loading && loading.style.display !== 'none') {
            loading.innerHTML = `<p class="dicom-modal-error">${t('files.viewer_failed', 'Viewer failed to load.')} <a href="#" onclick="location.reload()">${t('files.reload_link', 'Reload')}</a></p>`;
        }
    }, 15000);
}

// ── Custom file picker (replaces the browser's native file widget) ───────────

/**
 * Keep the custom file-picker label in sync with the selected file and
 * clear it back to the translated "no file chosen" string when empty.
 */
function _bindFilePicker() {
    const input = document.getElementById('fileInput');
    const nameEl = document.getElementById('fileInputName');
    if (!input || !nameEl) return;

    const sync = () => {
        const file = input.files && input.files[0];
        if (file) {
            nameEl.textContent = file.name;
            nameEl.classList.add('has-file');
            nameEl.removeAttribute('data-i18n');
        } else {
            _resetFilePickerName(nameEl);
        }
    };

    input.addEventListener('change', sync);
    sync();
}

function _resetFilePickerName(nameEl) {
    const el = nameEl || document.getElementById('fileInputName');
    if (!el) return;
    el.setAttribute('data-i18n', 'files.no_file_chosen');
    el.classList.remove('has-file');
    el.textContent = t('files.no_file_chosen', 'No file chosen');
}

// ── Initialisation ───────────────────────────────────────────────────────────

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

    _bindFilePicker();

    setInterval(loadFileList, FILE_REFRESH_INTERVAL);

    window.addEventListener('i18n:updated', () => {
        loadFileList();
        const input = document.getElementById('fileInput');
        if (input && (!input.files || !input.files.length)) {
            _resetFilePickerName();
        }
    });
}
