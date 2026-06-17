import { appState } from "./app-state.js";

const routes = {};

const PUBLIC_PATHS = new Set(["/login", "/register"]);

const ADMIN_ROLES = new Set(["admin", "super_admin"]);

export function registerRoute(path, handler) {
  routes[path] = handler;
}

function parseHash() {
  const hash = location.hash.replace(/^#/, "") || "/files";
  const [pathPart, query] = hash.split("?");
  const parts = pathPart.split("/").filter(Boolean);
  const params = Object.fromEntries(new URLSearchParams(query || ""));
  return { parts, params, path: "/" + parts.join("/") };
}

export function navigate(path) {
  location.hash = path.startsWith("#") ? path : `#${path}`;
}

export async function renderRoute() {
  const { params, path } = parseHash();
  const app = document.getElementById("app");

  if (PUBLIC_PATHS.has(path)) {
    await routes[path]?.(app, params);
    return;
  }

  if (!appState.isAuthenticated) {
    navigate("/login");
    return;
  }

  if (path.startsWith("/admin") && !ADMIN_ROLES.has(appState.role)) {
    navigate("/files");
    return;
  }

  const handler = routes[path];
  if (handler) {
    await handler(app, params);
    return;
  }

  navigate("/files");
}

export function initRouter() {
  window.addEventListener("hashchange", () => void renderRoute());
}
