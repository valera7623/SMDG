import { mountShell } from "../layout.js";
import {
  loadUserStats,
  loadUsers,
  applyFilters,
  clearFilters,
  debounceSearch,
  toggleAllCheckboxes,
  selectAll,
  clearSelection,
  executeBulkAction,
  showCreateUserModal,
  editUser,
  closeUserModal,
  handleUserSubmit,
  resetPassword,
  reset2FA,
  deleteUser,
} from "../modules/admin-users.js";
import { confirmAction, closeConfirmModal } from "../utils/modals.js";
import { t } from "../utils/i18n.js";

let usersPageBound = false;
let dlqTimer = null;

function bindUsersPageGlobals() {
  window.loadUsers = loadUsers;
  window.applyFilters = applyFilters;
  window.clearFilters = clearFilters;
  window.debounceSearch = debounceSearch;
  window.toggleAllCheckboxes = toggleAllCheckboxes;
  window.selectAll = selectAll;
  window.clearSelection = clearSelection;
  window.executeBulkAction = executeBulkAction;
  window.showCreateUserModal = showCreateUserModal;
  window.editUser = editUser;
  window.closeUserModal = closeUserModal;
  window.handleUserSubmit = handleUserSubmit;
  window.resetPassword = resetPassword;
  window.reset2FA = reset2FA;
  window.deleteUser = deleteUser;
  window.confirmAction = confirmAction;
  window.closeConfirmModal = closeConfirmModal;
}

export async function renderAdminUsers(root) {
  bindUsersPageGlobals();

  mountShell(
    root,
    t("admin_users.title", "Управление пользователями"),
    `
    <div class="page-header">
      <h1>${t("admin_users.title", "Управление пользователями")}</h1>
    </div>

    <div class="grid-4" style="margin-bottom:1rem">
      <div class="card"><div class="card-body"><small class="text-muted">${t("admin_users.stat_total", "Всего")}</small><div class="stat-value" id="totalUsers">0</div></div></div>
      <div class="card"><div class="card-body"><small class="text-muted">${t("admin_users.stat_active", "Активные")}</small><div class="stat-value" id="activeUsers">0</div></div></div>
      <div class="card"><div class="card-body"><small class="text-muted">${t("admin_users.stat_admins", "Админы")}</small><div class="stat-value" id="adminCount">0</div></div></div>
      <div class="card"><div class="card-body"><small class="text-muted">${t("admin_users.stat_2fa", "2FA")}</small><div class="stat-value" id="twofaCount">0</div></div></div>
    </div>
    <div class="grid-4" style="margin-bottom:1rem;display:none">
      <div class="card"><div class="card-body"><div class="stat-value" id="doctorCount">0</div></div></div>
      <div class="card"><div class="card-body"><div class="stat-value" id="userCount">0</div></div></div>
    </div>

    <div class="card filters" style="margin-bottom:1rem">
      <div class="form-row cols-2">
        <input type="text" id="searchInput" placeholder="${t("admin_users.search_placeholder", "Поиск…")}" oninput="debounceSearch()" />
        <div style="display:flex;gap:.5rem;flex-wrap:wrap">
          <select id="roleFilter" onchange="applyFilters()">
            <option value="">${t("admin_users.filter_all_roles", "Все роли")}</option>
            <option value="admin">${t("admin.role_admin", "Администратор")}</option>
            <option value="doctor">${t("admin.role_doctor", "Врач")}</option>
            <option value="user">${t("admin.role_user", "Пользователь")}</option>
          </select>
          <select id="statusFilter" onchange="applyFilters()">
            <option value="">${t("admin_users.filter_all_statuses", "Все статусы")}</option>
            <option value="active">${t("admin_users.stat_active", "Активные")}</option>
            <option value="inactive">${t("admin_users.filter_inactive", "Неактивные")}</option>
          </select>
          <button type="button" onclick="applyFilters()" class="btn btn-sm">${t("admin_users.apply", "Применить")}</button>
          <button type="button" onclick="clearFilters()" class="btn btn-outline btn-sm">${t("admin_users.clear_filters", "Сброс")}</button>
        </div>
      </div>
    </div>

    <div class="card" style="margin-bottom:1rem">
      <div class="card-body" style="display:flex;flex-wrap:wrap;gap:.5rem;align-items:center">
        <span id="selectedCount">${t("admin_users.selected", "Выбрано: 0")}</span>
        <button type="button" onclick="selectAll()" class="btn btn-outline btn-sm">${t("admin_users.select_all", "Выбрать все")}</button>
        <button type="button" onclick="clearSelection()" class="btn btn-outline btn-sm">${t("admin_users.clear_selection", "Снять выбор")}</button>
        <select id="bulkActionSelect">
          <option value="">${t("admin_users.bulk_actions", "Массовые действия")}</option>
          <option value="activate">${t("admin_users.bulk_activate", "Активировать")}</option>
          <option value="deactivate">${t("admin_users.bulk_deactivate", "Деактивировать")}</option>
          <option value="change_role">${t("admin_users.bulk_change_role", "Сменить роль")}</option>
          <option value="delete">${t("admin_users.bulk_delete", "Удалить")}</option>
        </select>
        <select id="bulkRoleSelect" hidden>
          <option value="user">${t("admin.role_user", "Пользователь")}</option>
          <option value="doctor">${t("admin.role_doctor", "Врач")}</option>
          <option value="admin">${t("admin.role_admin", "Администратор")}</option>
        </select>
        <button type="button" onclick="executeBulkAction()" class="btn btn-sm">${t("admin_users.execute", "Выполнить")}</button>
        <button type="button" onclick="showCreateUserModal()" class="btn btn-sm" style="margin-left:auto">➕ ${t("admin_users.create_new", "Создать")}</button>
      </div>
    </div>

    <div class="card">
      <div class="card-header"><h3>${t("admin_users.list_title", "Список пользователей")}</h3></div>
      <div class="card-body table-wrap">
        <table id="usersTable">
          <thead>
            <tr>
              <th><input type="checkbox" id="selectAllCheckbox" onchange="toggleAllCheckboxes()" /></th>
              <th>${t("admin_users.col_id", "ID")}</th>
              <th>${t("admin_users.col_username", "Имя")}</th>
              <th>${t("admin_users.col_email", "Email")}</th>
              <th>${t("admin_users.col_role", "Роль")}</th>
              <th>${t("admin_users.col_status", "Статус")}</th>
              <th>${t("admin_users.col_2fa", "2FA")}</th>
              <th class="td-actions">${t("admin_users.col_actions", "Действия")}</th>
            </tr>
          </thead>
          <tbody id="usersTableBody">
            <tr><td colspan="8" class="loading">${t("admin_users.loading_users", "Загрузка…")}</td></tr>
          </tbody>
        </table>
      </div>
      <div class="pagination" id="pagination"></div>
    </div>

    <div id="userModal" class="legacy-modal" style="display:none">
      <div class="modal-content card">
        <div class="card-header">
          <h3 id="modalTitle">${t("admin_users.modal_create", "Создать пользователя")}</h3>
          <button type="button" class="btn-icon" onclick="closeUserModal()">&times;</button>
        </div>
        <div class="card-body">
          <form id="userForm">
            <input type="hidden" id="userId" />
            <div class="form-group"><label for="modalUsername">${t("admin_users.col_username", "Имя")}</label><input id="modalUsername" required /></div>
            <div class="form-group"><label for="modalEmail">${t("admin_users.col_email", "Email")}</label><input id="modalEmail" type="email" required /></div>
            <div class="form-group" id="passwordGroup"><label for="modalPassword">${t("auth.password", "Пароль")}</label><input id="modalPassword" type="password" /></div>
            <div class="form-group"><label for="modalRole">${t("admin_users.col_role", "Роль")}</label>
              <select id="modalRole"><option value="user">${t("admin.role_user", "Пользователь")}</option><option value="doctor">${t("admin.role_doctor", "Врач")}</option><option value="admin">${t("admin.role_admin", "Админ")}</option></select>
            </div>
            <div class="form-group"><label><input type="checkbox" id="modalIsActive" checked /> ${t("admin_users.field_active", "Активен")}</label></div>
            <div class="form-group" id="reset2faGroup" hidden><label><input type="checkbox" id="modalReset2fa" /> ${t("admin_users.reset_2fa", "Сбросить 2FA")}</label></div>
            <div style="display:flex;gap:.5rem;justify-content:flex-end">
              <button type="button" class="btn btn-outline" onclick="closeUserModal()">${t("common.cancel", "Отмена")}</button>
              <button type="submit" class="btn" id="modalSubmitBtn">${t("admin_users.btn_create", "Создать")}</button>
            </div>
          </form>
        </div>
      </div>
    </div>

    <div id="confirmModal" class="legacy-modal" style="display:none">
      <div class="modal-content card" style="max-width:420px;margin:10vh auto">
        <div class="card-body">
          <h3 id="confirmTitle">${t("admin_users.confirm_title", "Подтверждение")}</h3>
          <p id="confirmMessage"></p>
          <div style="display:flex;gap:.5rem;justify-content:flex-end">
            <button type="button" class="btn btn-outline" onclick="closeConfirmModal()">${t("common.cancel", "Отмена")}</button>
            <button type="button" class="btn btn-danger" onclick="confirmAction()">${t("admin_users.btn_confirm", "Подтвердить")}</button>
          </div>
        </div>
      </div>
    </div>`,
    () => {
      if (!usersPageBound) {
        document.getElementById("bulkActionSelect")?.addEventListener("change", (e) => {
          const bulkRole = document.getElementById("bulkRoleSelect");
          if (bulkRole) bulkRole.hidden = e.target.value !== "change_role";
        });
        document.getElementById("userForm")?.addEventListener("submit", handleUserSubmit);
        usersPageBound = true;
      }
      loadUserStats();
      loadUsers();
    },
  );
}

export function stopDlqTimer() {
  if (dlqTimer) {
    clearInterval(dlqTimer);
    dlqTimer = null;
  }
}

export async function renderAdminDlq(root) {
  const {
    applyFilters,
    clearFilters,
    cleanupOld,
    deleteMessage,
    loadMessages,
    loadStats,
    nextPage,
    prevPage,
    replayMessage,
    viewMessage,
  } = await import("../modules/admin-dlq.js");

  window.loadMessages = loadMessages;
  window.applyFilters = applyFilters;
  window.viewMessage = viewMessage;
  window.replayMessage = replayMessage;
  window.deleteMessage = deleteMessage;
  window.cleanupOld = cleanupOld;
  window.clearFilters = clearFilters;
  window.nextPage = nextPage;
  window.prevPage = prevPage;

  mountShell(
    root,
    t("admin_dlq.title", "Dead Letter Queue"),
    `
    <div class="page-header"><h1>${t("admin_dlq.title", "Dead Letter Queue")}</h1></div>
    <div class="grid-4" id="statsGrid" style="margin-bottom:1rem"></div>
    <div class="card filters" style="margin-bottom:1rem">
      <div class="form-row cols-2">
        <input id="messageIdSearch" type="text" placeholder="${t("admin_dlq.search_placeholder", "Message ID")}" />
        <div style="display:flex;gap:.5rem;flex-wrap:wrap">
          <select id="statusFilter">
            <option value="">${t("admin_dlq.status_all", "Все статусы")}</option>
            <option value="pending">pending</option>
            <option value="processing">processing</option>
            <option value="failed">failed</option>
            <option value="resolved">resolved</option>
          </select>
          <select id="queueFilter">
            <option value="">${t("admin_dlq.queue_all", "Все очереди")}</option>
            <option value="webhook">webhook</option>
            <option value="email">email</option>
            <option value="cleanup">cleanup</option>
            <option value="dicom">dicom</option>
            <option value="audit">audit</option>
          </select>
          <select id="limitFilter">
            <option value="10">10</option>
            <option value="25" selected>25</option>
            <option value="50">50</option>
            <option value="100">100</option>
          </select>
          <button type="button" class="btn btn-sm" onclick="applyFilters()">${t("admin_dlq.apply", "Применить")}</button>
          <button type="button" class="btn btn-outline btn-sm" onclick="clearFilters()">${t("admin_dlq.reset", "Сброс")}</button>
        </div>
      </div>
      <p class="text-muted" id="autoRefreshInfo">${t("admin_dlq.auto_refresh", "Автообновление: каждые 10 секунд")}</p>
    </div>
    <div class="card" style="margin-bottom:1rem">
      <div class="card-body" style="display:flex;gap:.5rem;align-items:center;flex-wrap:wrap">
        <input id="cleanupDays" type="number" min="1" max="3650" value="30" style="width:6rem" />
        <button type="button" class="btn btn-sm" onclick="cleanupOld()">${t("admin_dlq.cleanup_old", "Очистить старые")}</button>
        <span id="maintenanceResult" class="text-muted"></span>
      </div>
    </div>
    <div class="card" style="margin-bottom:1rem">
      <div class="card-header"><h3>${t("admin_dlq.messages_title", "Сообщения")}</h3></div>
      <div class="card-body table-wrap">
        <table class="dlq-table">
          <thead>
            <tr>
              <th>${t("admin_dlq.col_message_id", "ID")}</th>
              <th>${t("admin_dlq.col_queue", "Очередь")}</th>
              <th>${t("admin_dlq.col_status", "Статус")}</th>
              <th>${t("admin_dlq.col_retries", "Повторы")}</th>
              <th>${t("admin_dlq.col_error", "Ошибка")}</th>
              <th>${t("admin_dlq.col_created", "Создано")}</th>
              <th>${t("admin_dlq.col_actions", "Действия")}</th>
            </tr>
          </thead>
          <tbody id="messagesTbody"><tr><td colspan="7" class="loading">${t("admin_dlq.loading", "Загрузка…")}</td></tr></tbody>
        </table>
      </div>
      <div class="pagination">
        <button type="button" class="btn btn-outline btn-sm" onclick="prevPage()">${t("admin_dlq.btn_prev", "← Назад")}</button>
        <span id="paginationInfo">Page 1</span>
        <button type="button" class="btn btn-outline btn-sm" onclick="nextPage()">${t("admin_dlq.btn_next", "Вперёд →")}</button>
      </div>
    </div>
    <div class="card">
      <div class="card-header"><h3>${t("admin_dlq.details_title", "Детали")}</h3></div>
      <div class="card-body"><pre id="detailsBox" class="json-viewer">{}</pre></div>
    </div>`,
    () => {
      document.getElementById("messageIdSearch")?.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          applyFilters();
        }
      });
      document.getElementById("limitFilter")?.addEventListener("change", () => applyFilters());
      loadStats();
      loadMessages();
      stopDlqTimer();
      dlqTimer = setInterval(() => {
        loadStats().catch(() => {});
        loadMessages().catch(() => {});
      }, 10000);
    },
  );
}
