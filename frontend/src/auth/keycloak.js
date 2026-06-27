import Keycloak from "keycloak-js";

const cfg = window.AEGIS_CONFIG || {};
export const keycloak = new Keycloak({
  url: cfg.KEYCLOAK_URL || "/auth",
  realm: cfg.REALM || "aegis",
  clientId: cfg.CLIENT_ID || "aegis-cli",
});

// initAuth() is called once from main.jsx. login-required makes Keycloak's
// hosted login page the single source of truth for credentials while keeping
// Authorization Code + PKCE in keycloak-js.
export async function initAuth() {
  return keycloak.init({
    onLoad: "login-required",
    pkceMethod: "S256",
    checkLoginIframe: false,
  });
}

// Kept for non-production experiments and older imports. The normal app boot
// path now redirects directly to Keycloak and never renders a React password UI.
export function signInWithKeycloak(email) {
  return keycloak.login({
    loginHint: email || undefined,
    redirectUri: window.location.origin,
  });
}

export function logout() {
  return keycloak.logout({
    redirectUri: window.location.origin,
  });
}
