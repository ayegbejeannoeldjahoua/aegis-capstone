import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import SignIn from "./pages/SignIn.jsx";
import { initAuth, keycloak } from "./auth/keycloak.js";
import "./styles.css";

const root = createRoot(document.getElementById("root"));

// Boot sequence:
//   1. initAuth() does a silent SSO check against Keycloak (no redirect).
//   2. If a session exists, render the authenticated Aegis app.
//   3. Otherwise render the branded landing page, which hands off to Keycloak.
initAuth()
  .then((authenticated) => {
    root.render(
      <React.StrictMode>
        {authenticated || keycloak.authenticated ? <App /> : <SignIn />}
      </React.StrictMode>
    );
  })
  .catch((e) => {
    root.render(
      <React.StrictMode>
        <div className="fatal">
          Authentication failed to initialize: {String(e?.message || e)}
        </div>
      </React.StrictMode>
    );
  });
