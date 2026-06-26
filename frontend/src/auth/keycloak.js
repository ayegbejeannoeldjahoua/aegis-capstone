import Keycloak from "keycloak-js";

const cfg = window.AEGIS_CONFIG || {};
export const keycloak = new Keycloak({
  url: cfg.KEYCLOAK_URL || "/auth",
  realm: cfg.REALM || "aegis",
  clientId: cfg.CLIENT_ID || "aegis-cli",
});

// initAuth() — called once from main.jsx at app boot.
//
// onLoad mode:
//   `check-sso`  -> Keycloak silently checks whether the user already has
//                   a Keycloak session (via a hidden iframe). If yes, the
//                   token is populated and `keycloak.authenticated` is true.
//                   If no, init resolves normally with `authenticated=false`
//                   and React renders the Aegis sign-in landing page.
//
// Previously this was `login-required`, which redirected EVERY page load
// to Keycloak's hosted login. That bypassed the Aegis-branded sign-in
// screen entirely. With `check-sso` we keep the security model (Keycloak
// still hosts the password collection) while giving us our own landing
// page in front.
export async function initAuth() {
  return keycloak.init({
    onLoad: "check-sso",
    pkceMethod: "S256",
    checkLoginIframe: false,
  });
}

// Hand off to Keycloak's hosted login page. `loginHint` pre-fills the
// username field on the Keycloak screen so the user only has to type
// their password once after typing their email on our landing page.
export function signInWithKeycloak(email) {
  const opts = {};
  if (email) opts.loginHint = email;
  keycloak.login(opts);
}

export function logout() {
  keycloak.logout({ redirectUri: window.location.origin });
}
