import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import { initAuth, keycloak } from "./auth/keycloak.js";
import { ThemeProvider } from "./theme/ThemeProvider.jsx";
import "./styles.css";

const root = createRoot(document.getElementById("root"));

function AuthSplash() {
  return (
    <div className="auth-splash" role="status" aria-live="polite">
      <div className="auth-splash-mark">A</div>
      <div>
        <div className="auth-splash-title">Aegis</div>
        <div className="auth-splash-subtitle">Redirecting to secure sign in</div>
      </div>
    </div>
  );
}

root.render(
  <React.StrictMode>
    <ThemeProvider>
      <AuthSplash />
    </ThemeProvider>
  </React.StrictMode>
);

// Boot sequence:
//   1. initAuth() uses login-required, so unauthenticated users go straight
//      to Keycloak's hosted login page.
//   2. After Keycloak redirects back with an authenticated session, render
//      the Aegis app. React never collects or submits passwords.
initAuth()
  .then(() => {
    root.render(
      <React.StrictMode>
        <ThemeProvider>
          {keycloak.authenticated ? <App /> : <AuthSplash />}
        </ThemeProvider>
      </React.StrictMode>
    );
  })
  .catch((e) => {
    root.render(
      <React.StrictMode>
        <ThemeProvider>
          <div className="fatal">
            Authentication failed to initialize: {String(e?.message || e)}
          </div>
        </ThemeProvider>
      </React.StrictMode>
    );
  });
