import { currentLocale, t } from "../utils/i18n.js";

const tbody = () => document.getElementById("messagesTbody");
const detailsBox = () => document.getElementById("detailsBox");
const statsGrid = () => document.getElementById("statsGrid");
const paginationInfo = () => document.getElementById("paginationInfo");

let currentOffset = 0;
let currentLimit = 25;
let currentTotal = 0;

function esc(text) {
    return String(text ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;");
}

function fmtDate(value) {
    if (!value) return "-";
    try {
        return new Date(value).toLocaleString(currentLocale());
    } catch {
        return value;
    }
}

async function api(path, options = {}) {
    const response = await fetch(path, {
        credentials: "include",
        ...options,
        headers: {
            "Content-Type": "application/json",
            ...(options.headers || {}),
        },
    });

    if (!response.ok) {
        const text = await response.text();
        throw new Error(text || `HTTP ${response.status}`);
    }

    if (response.status === 204) return null;
    return await response.json();
}

export async function loadStats() {
    const grid = statsGrid();
    if (!grid) return;

    const stats = await api("/api/dlq/stats");
    const rows = [
        [t("admin_dlq.stat_total", "Total"), stats.total ?? 0],
        [t("admin_dlq.stat_pending", "Pending"), stats.pending ?? 0],
        [t("admin_dlq.stat_processing", "Processing"), stats.processing ?? 0],
        [t("admin_dlq.stat_failed", "Failed"), stats.failed ?? 0],
        [t("admin_dlq.stat_resolved", "Resolved"), stats.resolved ?? 0],
    ];
    grid.innerHTML = rows
        .map(([label, value]) => `<div class="stat-card"><div>${esc(label)}</div><div class="value">${value}</div></div>`)
        .join("");
}

function currentFilters() {
    const status = document.getElementById("statusFilter").value;
    const queue_name = document.getElementById("queueFilter").value;
    const message_id = document.getElementById("messageIdSearch").value.trim();
    currentLimit = Number(document.getElementById("limitFilter").value || 25);
    const params = new URLSearchParams();
    if (status) params.set("status", status);
    if (queue_name) params.set("queue_name", queue_name);
    if (message_id) params.set("message_id", message_id);
    params.set("limit", String(currentLimit));
    params.set("offset", String(currentOffset));
    return params.toString();
}

export async function loadMessages() {
    const body = tbody();
    const pinfo = paginationInfo();
    if (!body) return;

    body.innerHTML = `<tr><td colspan="7" class="loading">${esc(
        t("admin_dlq.loading", "Loading…"),
    )}</td></tr>`;
    const query = currentFilters();
    const data = await api(`/api/dlq/messages?${query}`);
    const messages = data.messages || [];
    currentTotal = Number(data.total || 0);
    const page = Math.floor(currentOffset / currentLimit) + 1;
    const totalPages = Math.max(1, Math.ceil(currentTotal / currentLimit));
    if (pinfo) {
        pinfo.textContent = t(
            "admin_dlq.page_info",
            "Page {{page}} of {{totalPages}} (total: {{total}})",
            {
                page: String(page),
                totalPages: String(totalPages),
                total: String(currentTotal),
            },
        );
    }

    if (!messages.length) {
        if (currentOffset > 0 && currentTotal > 0) {
            currentOffset = Math.max(0, currentOffset - currentLimit);
            await loadMessages();
            return;
        }
        body.innerHTML = `<tr><td colspan="7" class="loading">${esc(
            t("admin_dlq.no_messages", "No messages found"),
        )}</td></tr>`;
        return;
    }

    const labId = t("admin_dlq.col_message_id", "Message ID");
    const labQueue = t("admin_dlq.col_queue", "Queue");
    const labStatus = t("admin_dlq.col_status", "Status");
    const labRetries = t("admin_dlq.col_retries", "Retries");
    const labError = t("admin_dlq.col_error", "Error");
    const labCreated = t("admin_dlq.col_created", "Created");
    const labActions = t("admin_dlq.col_actions", "Actions");
    const txtView = t("admin_dlq.btn_view", "View");
    const txtReplay = t("admin_dlq.btn_replay", "Replay");
    const txtDelete = t("admin_dlq.btn_delete", "Delete");

    body.innerHTML = "";
    messages.forEach((message) => {
        body.appendChild(_createMessageRow(message, {
            labId,
            labQueue,
            labStatus,
            labRetries,
            labError,
            labCreated,
            labActions,
            txtView,
            txtReplay,
            txtDelete,
        }));
    });
}

function _td(label, text) {
    const cell = document.createElement("td");
    cell.setAttribute("data-label", label);
    cell.textContent = String(text ?? "");
    return cell;
}

function _createMessageRow(message, labels) {
    const tr = document.createElement("tr");
    const messageId = String(message.message_id ?? "");

    const idCell = document.createElement("td");
    idCell.setAttribute("data-label", labels.labId);
    const code = document.createElement("code");
    code.textContent = messageId;
    idCell.appendChild(code);
    tr.appendChild(idCell);

    tr.appendChild(_td(labels.labQueue, message.queue_name));

    const statusCell = document.createElement("td");
    statusCell.setAttribute("data-label", labels.labStatus);
    const status = document.createElement("span");
    status.className = `status-badge ${String(message.status ?? "").replace(/[^a-z0-9_-]/gi, "")}`;
    status.textContent = String(message.status ?? "");
    statusCell.appendChild(status);
    tr.appendChild(statusCell);

    tr.appendChild(_td(labels.labRetries, `${message.retry_count ?? 0}/${message.max_retries ?? 0}`));
    tr.appendChild(_td(labels.labError, String(message.error_message || "").slice(0, 120)));
    tr.appendChild(_td(labels.labCreated, fmtDate(message.created_at)));

    const actionsCell = document.createElement("td");
    actionsCell.setAttribute("data-label", labels.labActions);
    const actions = document.createElement("div");
    actions.className = "actions";

    const addAction = (className, text, handler) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = `action-btn ${className}`;
        button.textContent = text;
        button.addEventListener("click", () => handler(messageId));
        actions.appendChild(button);
    };

    addAction("view", labels.txtView, viewMessage);
    addAction("replay", labels.txtReplay, replayMessage);
    addAction("delete", labels.txtDelete, deleteMessage);
    actionsCell.appendChild(actions);
    tr.appendChild(actionsCell);

    return tr;
}

export async function viewMessage(messageId) {
    const data = await api(`/api/dlq/messages/${encodeURIComponent(messageId)}`);
    const box = detailsBox();
    if (box) box.textContent = JSON.stringify(data, null, 2);
}

export async function replayMessage(messageId) {
    await api(`/api/dlq/messages/${encodeURIComponent(messageId)}/replay`, { method: "POST" });
    await Promise.all([loadStats(), loadMessages()]);
}

export async function deleteMessage(messageId) {
    if (
        !window.confirm(
            t("admin_dlq.delete_confirm", "Delete DLQ message {{id}}?", { id: messageId }),
        )
    )
        return;
    await api(`/api/dlq/messages/${encodeURIComponent(messageId)}`, { method: "DELETE" });
    const box = detailsBox();
    if (box) box.textContent = "{}";
    await Promise.all([loadStats(), loadMessages()]);
}

export async function cleanupOld() {
    const days = Number(document.getElementById("cleanupDays").value || 30);
    const result = await api(`/api/dlq/cleanup?days=${days}`, { method: "POST" });
    const el = document.getElementById("maintenanceResult");
    if (el) {
        el.textContent = t("admin_dlq.deleted_count", "Deleted: {{count}}", {
            count: String(result.deleted ?? 0),
        });
    }
    await Promise.all([loadStats(), loadMessages()]);
}

export function clearFilters() {
    currentOffset = 0;
    document.getElementById("statusFilter").value = "";
    document.getElementById("queueFilter").value = "";
    document.getElementById("messageIdSearch").value = "";
    document.getElementById("limitFilter").value = "25";
    loadMessages();
}

export function nextPage() {
    const nextOffset = currentOffset + currentLimit;
    if (nextOffset >= currentTotal) return;
    currentOffset = nextOffset;
    loadMessages();
}

export function prevPage() {
    currentOffset = Math.max(0, currentOffset - currentLimit);
    loadMessages();
}

export function applyFilters() {
    currentOffset = 0;
    loadMessages();
}
