import Keycloak from "keycloak-js";

const cfg = window.AEGIS_CONFIG || {};
export const keycloak = new Keycloak({
  url: cfg.KEYCLOAK_URL || "http://localhost:8081",
  realm: cfg.REALM || "aegis",
  clientId: cfg.CLIENT_ID || "aegis-cli",
});

export async function initAuth() {
  return keycloak.init({
    onLoad: "login-required",
    pkceMethod: "S256",
    checkLoginIframe: false,
  });
}

export function logout() {
  keycloak.logout({ redirectUri: window.location.origin });
}
