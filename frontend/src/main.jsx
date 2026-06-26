import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import SignIn from "./pages/SignIn.jsx";
import { initAuth, keycloak } from "./auth/keycloak.js";
import "./styles.css";

const root = createRoot(document.getElementById("root"));

// Boot sequence:
//   1. initAuth() does a silent SSO check against Keycloak (no redirect).
//   2. If a valid session already exists -> render <App /> (logged in).
//   3. Otherwise -> render <SignIn />, the Aegis-branded landing page.
//      The user types their email, clicks "Sign in", and we hand off
//      to Keycloak (which collects the password and runs the OIDC flow).
//   4. After Keycloak completes, the browser returns to the same URL,
//      initAuth() finds the session, and step 2 renders <App />.
initAuth()
  .then(() => {
    if (keycloak.authenticated) {
      root.render(<App />);
    } else {
      root.render(<SignIn />);
    }
  })
  .catch((e) => {
    root.render(
      <div className="fatal">
        Sign-in service unreachable: {String(e)}
      </div>
    );
  });
