import { keycloak } from "../auth/keycloak.js";

const cfg = window.AEGIS_CONFIG || {};
const API_BASE = cfg.API_BASE || "http://localhost:8080";
const ADMIN_KEY = "aegis_admin_token";

export function getAdminToken() {
  return localStorage.getItem(ADMIN_KEY) || "";
}
export function setAdminToken(v) {
  localStorage.setItem(ADMIN_KEY, v || "");
}

// In-memory profile from /v1/me (the caller's role + admin capabilities).
let _profile = null;
export function getProfile() { return _profile; }
export function setProfile(p) { _profile = p; }

// Admin surfaces are available if the logged-in user has an admin_scope, OR a shared
// admin token has been supplied (ops override).
export function canAdmin() {
  if (getAdminToken()) return true;
  return !!(_profile && _profile.admin_scope && _profile.admin_scope !== "none");
}

export async function api(path, { method = "GET", body, admin = false } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (admin && getAdminToken()) {
    headers["X-Admin-Token"] = getAdminToken();  // explicit ops override
  } else {
    try { await keycloak.updateToken(30); } catch (_) { /* request will 401 */ }
    headers["Authorization"] = `Bearer ${keycloak.token}`;  // OIDC bearer (admin via admin_scope)
  }
  const res = await fetch(`${API_BASE}${path}`, {
    method, headers, body: body ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  let data;
  try { data = text ? JSON.parse(text) : null; } catch (_) { data = text; }
  if (!res.ok) {
    const msg = (data && (data.error || data.detail)) || res.statusText || `HTTP ${res.status}`;
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return data;
}

export async function fetchMe() {
  const p = await api("/v1/me");
  setProfile(p);
  return p;
}
