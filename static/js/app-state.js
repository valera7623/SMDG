const THEME_KEY = "smdg_theme";

const listeners = new Set();

export const appState = {
  username: null,
  role: null,
  isAdmin: false,
  isAuthenticated: false,
  theme: localStorage.getItem(THEME_KEY) || "light",
  sidebarOpen: false,
};

export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

function notify() {
  listeners.forEach((fn) => fn(appState));
}

export function setUser(username, role) {
  appState.username = username;
  appState.role = role;
  appState.isAdmin = role === "admin" || role === "super_admin";
  appState.isAuthenticated = !!username;
  notify();
}

export function clearUser() {
  appState.username = null;
  appState.role = null;
  appState.isAdmin = false;
  appState.isAuthenticated = false;
  notify();
}

export function setTheme(theme) {
  localStorage.setItem(THEME_KEY, theme);
  appState.theme = theme;
  document.documentElement.dataset.theme = theme;
  notify();
}

export function toggleTheme() {
  setTheme(appState.theme === "dark" ? "light" : "dark");
}

export function toggleSidebar(open) {
  appState.sidebarOpen = open ?? !appState.sidebarOpen;
  notify();
}

export function initAppState() {
  document.documentElement.dataset.theme = appState.theme;
}
