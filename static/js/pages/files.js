import { mountShell } from "../layout.js";
import { initFiles, loadFileList, handleFileUpload } from "../modules/files.js";
import { handleSetup2FA } from "../modules/auth.js";
import { t } from "../utils/i18n.js";

let filesInterval = null;

function bindFilePicker() {
  const input = document.getElementById("fileInput");
  const nameEl = document.getElementById("fileInputName");
  if (!input || !nameEl) return;
  input.addEventListener("change", () => {
    nameEl.textContent = input.files?.[0]?.name || t("files.no_file_chosen", "Файл не выбран");
  });
}

export async function renderFiles(root) {
  mountShell(
    root,
    t("files.list", "Файлы"),
    `
    <div class="page-header">
      <h1>${t("files.upload", "Загрузка файла")}</h1>
      <p>${t("system.info_encrypt", "Все файлы шифруются при загрузке")}</p>
    </div>

    <div class="card" style="margin-bottom:1rem">
      <div class="card-body">
        <div class="badge badge-success" style="margin-bottom:.75rem">✅ ${t("system.running", "Система работает")}</div>
        <form id="uploadForm">
          <div class="form-group file-picker">
            <input type="file" id="fileInput" class="file-picker__input" required />
            <label for="fileInput" class="btn btn-outline file-picker__button">${t("files.choose_file", "Выбрать файл")}</label>
            <span id="fileInputName" class="file-picker__name text-muted">${t("files.no_file_chosen", "Файл не выбран")}</span>
          </div>
          <button type="submit" class="btn">${t("files.upload_button", "Загрузить")}</button>
        </form>
        <div id="uploadResult"></div>
      </div>
    </div>

    <div class="card">
      <div class="card-header">
        <h3>${t("files.list", "Список файлов")}</h3>
        <button type="button" id="refreshBtn" class="btn btn-outline btn-sm">🔄 ${t("common.refresh", "Обновить")}</button>
      </div>
      <div class="card-body">
        <div id="fileList" class="file-list"></div>
      </div>
    </div>

    <div class="card" style="margin-top:1rem">
      <div class="card-header"><h3>${t("system.info_heading", "О системе")}</h3></div>
      <div class="card-body text-muted" style="font-size:.9rem">
        <ul class="info-list">
          <li>${t("system.info_encrypt", "Все файлы шифруются при загрузке")}</li>
          <li>${t("system.info_retention", "Зашифрованные файлы хранятся 30 дней")}</li>
          <li>${t("system.info_audit", "Все операции логируются для аудита")}</li>
        </ul>
        <button type="button" id="setup2faDashboardBtn" class="btn btn-outline btn-sm" style="margin-top:.75rem">${t("auth.2fa_setup", "Настроить 2FA")}</button>
      </div>
    </div>`,
    (shellRoot) => {
      shellRoot.querySelector("#uploadForm")?.addEventListener("submit", handleFileUpload);
      shellRoot.querySelector("#refreshBtn")?.addEventListener("click", loadFileList);
      shellRoot.querySelector("#setup2faDashboardBtn")?.addEventListener("click", handleSetup2FA);
      bindFilePicker();
      loadFileList();
      if (filesInterval) clearInterval(filesInterval);
      filesInterval = setInterval(loadFileList, 30000);
    },
  );
}
