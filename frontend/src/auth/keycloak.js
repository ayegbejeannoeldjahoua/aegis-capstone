import Keycloak from "keycloak-js";

const cfg = window.AEGIS_CONFIG || {};
export const keycloak = new Keycloak({
  url: cfg.KEYCLOAK_URL || "/auth",
  realm: cfg.REALM || "aegis",
  clientId: cfg.CLIENT_ID || "aegis-cli",
});

// initAuth() is called once from main.jsx. check-sso lets the React sign-in
// landing page render when there is no Keycloak session instead of forcing an
// immediate redirect loop.
export async function initAuth() {
  return keycloak.init({
    onLoad: "check-sso",
    pkceMethod: "S256",
    checkLoginIframe: false,
  });
}

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
