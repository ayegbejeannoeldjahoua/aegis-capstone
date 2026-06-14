import React, { useEffect, useState } from "react";
import { keycloak, logout } from "./auth/keycloak.js";
import { canAdmin, fetchMe, getAdminToken, getProfile, setAdminToken } from "./api/client.js";
import Tenants from "./pages/Tenants.jsx";
import MCP from "./pages/MCP.jsx";
import Users from "./pages/Users.jsx";
import Governance from "./pages/Governance.jsx";
import Values from "./pages/Values.jsx";
import Account from "./pages/Account.jsx";
import Audit from "./pages/Audit.jsx";
import Models from "./pages/Models.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import FinOps from "./pages/FinOps.jsx";
import PolicyExplorer from "./pages/PolicyExplorer.jsx";
import Runs from "./pages/Runs.jsx";

export default function Console({ onHome }) {
  const [profile, setProfile] = useState(getProfile());
  const [tab, setTab] = useState("values");
  const [adminTok, setTok] = useState(getAdminToken());
  const claims = keycloak.tokenParsed || {};

  useEffect(() => {
    fetchMe().then((p) => {
      setProfile(p);
      if (p.admin_scope && p.admin_scope !== "none") setTab("dashboard");
    }).catch(() => setProfile(getProfile()));
  }, []);

  function saveAdmin(v) { setAdminToken(v); setTok(v); }

  const admin = canAdmin();
  const platformAdmin = (profile && profile.admin_scope === "platform") || !!adminTok;
  const tabs = [["values", "Values"], ["account", "Account"]];
  if (admin) tabs.unshift(
    ["dashboard", "Dashboard"],
    ["runs", "Runs"],
    ["finops", "FinOps"],
    ["policy", "Policy"],
    ["tenants", "Tenants"],
    ["users", "Users"],
    ["governance", "Governance"],
    ["audit", "Audit"],
  );
  if (platformAdmin) tabs.push(["models", "Models"], ["mcp", "MCP"]);

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">Aegis<span>AI Governance Platform</span></div>
        <button className="ghost home-link" onClick={onHome}>← Home</button>
        <nav>
          {tabs.map(([k, label]) => (
            <button key={k} className={tab === k ? "active" : ""} onClick={() => setTab(k)}>{label}</button>
          ))}
        </nav>
        <div className="admin-token">
          <label>Admin token (optional)</label>
          <input type="password" value={adminTok} placeholder="ops override"
                 onChange={(e) => saveAdmin(e.target.value)} />
          <small>Admin access normally comes from your role's scope. This token is a super-admin override.</small>
        </div>
      </aside>
      <main>
        <header className="topbar">
          <div className="who">
            {profile ? profile.email : (claims.email || "user")}
            {profile && <span className="role-badge">{profile.role} {profile.admin_scope}</span>}
          </div>
          <button className="ghost" onClick={logout}>Log out</button>
        </header>
        <section className="content">
          {tab === "dashboard" && admin && <Dashboard />}
          {tab === "runs" && admin && <Runs />}
          {tab === "finops" && admin && <FinOps />}
          {tab === "policy" && admin && <PolicyExplorer />}
          {tab === "tenants" && admin && <Tenants />}
          {tab === "users" && admin && <Users />}
          {tab === "governance" && admin && <Governance />}
          {tab === "values" && <Values />}
          {tab === "audit" && admin && <Audit />}
          {tab === "mcp" && platformAdmin && <MCP />}
          {tab === "models" && platformAdmin && <Models />}
          {tab === "account" && <Account />}
        </section>
      </main>
    </div>
  );
}
