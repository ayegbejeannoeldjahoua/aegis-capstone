import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import { initAuth } from "./auth/keycloak.js";
import "./styles.css";

const root = createRoot(document.getElementById("root"));
initAuth()
  .then(() => root.render(<App />))
  .catch((e) => {
    root.render(<div className="fatal">Sign-in failed: {String(e)}</div>);
  });
