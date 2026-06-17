import { mountShell } from "../layout.js";
import { loadFiles, loadSystemStats, getCleanupStats, purgeAllFiles } from "../modules/admin-files.js";
import { initFileAudit } from "../modules/admin-file-audit.js";
import { t } from "../utils/i18n.js";

let auditInitialized = false;

export async function renderAdminFiles(root) {
  mountShell(
    root,
    t("admin.title", "Админ-панель"),
    `
    <div class="page-header">
      <h1>${t("admin.files_section", "Управление файлами")}</h1>
      <p class="text-muted">${t("admin.users_description", "Просмотр, создание и удаление данных системы")}</p>
    </div>

    <div class="card" style="margin-bottom:1rem">
      <div class="card-header">
        <h3>${t("admin.files_section", "Файлы")}</h3>
        <div style="display:flex;gap:.5rem;flex-wrap:wrap">
          <button type="button" class="btn btn-outline btn-sm" data-action="refresh-files">🔄 ${t("admin.refresh_list", "Обновить")}</button>
          <button type="button" class="btn btn-sm" data-action="cleanup-stats">🚮 ${t("admin.check_cleanup", "Проверить очистку")}</button>
        </div>
      </div>
      <div class="card-body">
        <div id="fileList" class="file-list admin"></div>
        <div id="cleanupStats"></div>
      </div>
    </div>

    <div class="card" style="margin-bottom:1rem">
      <div class="card-header"><h3>${t("admin_file_audit.title", "Журнал аудита файлов")}</h3></div>
      <div class="card-body">
        <div class="filters card" style="margin-bottom:1rem;padding:1rem">
          <div class="form-row cols-2" style="margin-bottom:.75rem">
            <div class="form-group" style="margin:0">
              <input id="fileAuditSearch" type="search" placeholder="${t("admin_file_audit.search_placeholder", "Пользователь, файл или IP")}" />
            </div>
            <div class="form-group" style="margin:0">
              <select id="fileAuditAction">
                <option value="">${t("admin_file_audit.action_all", "Все действия")}</option>
                <option value="upload">${t("admin_file_audit.action_upload", "Загрузка")}</option>
                <option value="download_authenticated">${t("admin_file_audit.action_download_user", "Скачивание")}</option>
                <option value="download_token">${t("admin_file_audit.action_download_link", "Ссылка")}</option>
              </select>
            </div>
          </div>
          <div class="form-row cols-4">
            <select id="fileAuditSuccess">
              <option value="">${t("admin_file_audit.status_all", "Все статусы")}</option>
              <option value="true">${t("admin_file_audit.status_success", "Успех")}</option>
              <option value="false">${t("admin_file_audit.status_failed", "Ошибка")}</option>
            </select>
            <input id="fileAuditStart" type="datetime-local" />
            <input id="fileAuditEnd" type="datetime-local" />
            <div style="display:flex;gap:.5rem">
              <button type="button" id="fileAuditRefresh" class="btn btn-outline btn-sm">${t("admin_file_audit.refresh", "Обновить")}</button>
              <button type="button" id="fileAuditReset" class="btn btn-outline btn-sm">${t("admin_file_audit.reset_filters", "Сброс")}</button>
            </div>
          </div>
        </div>
        <div id="fileAuditList"></div>
      </div>
    </div>

    <div class="card" style="margin-bottom:1rem">
      <div class="card-header"><h3>${t("admin.system_stats", "Статистика системы")}</h3></div>
      <div class="card-body" id="statsInfo"></div>
    </div>

    <div class="card" id="admin-danger-wrap">
      <div class="card-header"><h3>⚠️ ${t("admin.danger_ops", "Опасные операции")}</h3></div>
      <div class="card-body">
        <p class="text-muted">${t("admin.delete_all_warning", "Удаляет все зашифрованные файлы. Требуется двойное подтверждение.")}</p>
        <button type="button" class="btn btn-danger" data-action="purge-all">🗑️ ${t("admin.delete_all_files", "УДАЛИТЬ ВСЕ ФАЙЛЫ")}</button>
      </div>
    </div>`,
    (shellRoot) => {
      shellRoot.querySelector('[data-action="refresh-files"]')?.addEventListener("click", loadFiles);
      shellRoot.querySelector('[data-action="cleanup-stats"]')?.addEventListener("click", getCleanupStats);
      shellRoot.querySelector('[data-action="purge-all"]')?.addEventListener("click", purgeAllFiles);
      if (!auditInitialized) {
        initFileAudit();
        auditInitialized = true;
      }
      loadFiles();
      loadSystemStats();
    },
  );
}
