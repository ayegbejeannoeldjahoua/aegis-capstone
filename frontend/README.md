# Aegis AI Governance Platform — Web UI

A Vite + React single-page app. Authenticates via Keycloak (OIDC auth-code + PKCE,
public client `aegis-cli`) and calls the API. Host-agnostic: the same build can be
served as a website or wrapped (e.g. Tauri) as a desktop app later.

## Run (via docker compose, from the project root)

```bash
docker compose up -d --build frontend
# open http://localhost:5173  (log in as jane / password)
```

The `frontend` service builds the bundle and serves it with nginx on host port 5173.

## Local dev (hot reload, outside Docker)

```bash
cd frontend && npm install && npm run dev   # http://localhost:5173
```

## Runtime config

`public/config.js` sets `API_BASE`, `KEYCLOAK_URL`, `REALM`, `CLIENT_ID`. Defaults target
the local stack (API :8080, Keycloak :8081). Override it per environment without rebuilding.

## Screens

- **Tenants** — list/create tenants and inspect their roles/capabilities (calls the
  `X-Admin-Token`-guarded `/admin/tenants` API; paste the admin token in the sidebar).
- **Test Console** — run a governed `/v1/ask` as the logged-in user and view the per-action
  audit trace (allow/deny decisions), including the prompt-injection containment demo.
