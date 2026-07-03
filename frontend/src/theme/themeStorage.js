export const THEME_STORAGE_KEY = "aegis.theme";
export const THEMES = ["dark", "light"];

export function normalizeTheme(value) {
  return THEMES.includes(value) ? value : "dark";
}

export function readStoredTheme(storage) {
  try {
    const source = storage ?? globalThis.localStorage;
    return normalizeTheme(source?.getItem(THEME_STORAGE_KEY));
  } catch (_) {
    return "dark";
  }
}

export function writeStoredTheme(theme, storage) {
  const next = normalizeTheme(theme);
  try {
    const source = storage ?? globalThis.localStorage;
    source?.setItem(THEME_STORAGE_KEY, next);
  } catch (_) {
    // Persistence is best-effort. The applied theme still updates in memory.
  }
  return next;
}

export function applyDocumentTheme(theme, root = globalThis.document?.documentElement) {
  const next = normalizeTheme(theme);
  if (root) root.setAttribute("data-theme", next);
  return next;
}
