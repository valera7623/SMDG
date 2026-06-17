export function toast(message, type = "info") {
  const el = document.createElement("div");
  el.className = `toast toast-${type}`;
  el.textContent = message;
  document.getElementById("toast-container").appendChild(el);
  setTimeout(() => el.classList.add("show"), 10);
  setTimeout(() => {
    el.classList.remove("show");
    setTimeout(() => el.remove(), 300);
  }, 3500);
}

export function showModal({ title, body, footer }) {
  return new Promise((resolve) => {
    const root = document.getElementById("modal-root");
    const overlay = document.createElement("div");
    overlay.className = "modal-overlay";
    overlay.innerHTML = `
      <div class="modal" role="dialog">
        <div class="modal-header">
          <h3>${title}</h3>
          <button type="button" class="btn-icon modal-close" aria-label="Закрыть">&times;</button>
        </div>
        <div class="modal-body">${body}</div>
        <div class="modal-footer">${footer || ""}</div>
      </div>`;
    root.appendChild(overlay);
    const close = (result) => {
      overlay.remove();
      resolve(result);
    };
    overlay.querySelector(".modal-close").onclick = () => close(false);
    overlay.addEventListener("click", (e) => {
      if (e.target === overlay) close(false);
    });
    overlay.querySelectorAll("[data-modal-action]").forEach((btn) => {
      btn.onclick = () => close(btn.dataset.modalAction);
    });
  });
}

export async function confirmDialog(title, text) {
  const body = `<p class="text-muted">${text}</p>`;
  const footer = `
    <button type="button" class="btn btn-outline" data-modal-action="false">Отмена</button>
    <button type="button" class="btn btn-danger" data-modal-action="true">Подтвердить</button>`;
  return (await showModal({ title, body, footer })) === "true";
}

export function loadingHtml(text = "Загрузка...") {
  return `<div class="loading"><div class="spinner"></div><p>${text}</p></div>`;
}

export function emptyState(text) {
  return `<p class="empty-state">${text}</p>`;
}
