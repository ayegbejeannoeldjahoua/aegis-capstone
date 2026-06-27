import React, { useEffect, useState } from "react";
import {
  Building2,
  Cpu,
  DollarSign,
  FileText,
  Gavel,
  Heart,
  Home,
  KeyRound,
  LayoutDashboard,
  Play,
  Server,
  Settings,
  Shield,
  User,
  Users as UsersIcon,
} from "lucide-react";
import { keycloak, logout } from "./auth/keycloak.js";
import { canAdmin, fetchMe, getAdminToken, getProfile, setAdminToken } from "./api/client.js";
import { AegisButton, AegisLogo, ShellTopBar, cx } from "./components/figma/AegisPrimitives.jsx";
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

const TAB_META = {
  dashboard: { icon: LayoutDashboard, section: "Console / Dashboard" },
  runs: { icon: Play, section: "Console / Runs" },
  finops: { icon: DollarSign, section: "Console / FinOps" },
  policy: { icon: Shield, section: "Console / Policy" },
  tenants: { icon: Building2, section: "Console / Tenants" },
  users: { icon: UsersIcon, section: "Console / Users" },
  governance: { icon: Gavel, section: "Console / Governance" },
  audit: { icon: FileText, section: "Console / Audit" },
  values: { icon: Heart, section: "Console / Values" },
  account: { icon: User, section: "Console / Account" },
  models: { icon: Cpu, section: "Console / Models" },
  mcp: { icon: Server, section: "Console / MCP" },
};

export default function Console({ onHome, initialTab }) {
  const [profile, setProfile] = useState(getProfile());
  const [tab, setTab] = useState(initialTab || "values");
  const [adminTok, setTok] = useState(getAdminToken());
  const claims = keycloak.tokenParsed || {};

  useEffect(() => {
    fetchMe().then((p) => {
      setProfile(p);
      if (!initialTab && p.admin_scope && p.admin_scope !== "none") setTab("dashboard");
    }).catch(() => setProfile(getProfile()));
  }, [initialTab]);

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
  const activeTab = tabs.some(([k]) => k === tab) ? tab : "values";
  const activeLabel = tabs.find(([k]) => k === activeTab)?.[1] || "Values";

  return (
    <div className="app aegis-shell">
      <aside className="aegis-sidebar">
        <div className="aegis-sidebar-brand">
          <AegisLogo />
        </div>
        <AegisButton variant="sidebar" icon={Home} onClick={onHome}>
          Home
        </AegisButton>
        <div className="aegis-nav-label">Navigation</div>
        <nav aria-label="Console sections" className="aegis-sidebar-nav">
          {tabs.map(([k, label]) => (
            <button
              key={k}
              className={cx("aegis-nav-item", activeTab === k && "active")}
              onClick={() => setTab(k)}
              type="button"
            >
              {React.createElement(TAB_META[k]?.icon || Settings, { size: 13 })}
              <span>{label}</span>
            </button>
          ))}
        </nav>
        <details className="aegis-admin-token">
          <summary>
            <KeyRound size={11} />
            <span>Admin token</span>
          </summary>
          <label>
            <span>Ops override</span>
            <input type="password" value={adminTok} placeholder="optional"
                   onChange={(e) => saveAdmin(e.target.value)} />
          </label>
          <small>Admin access normally comes from your role scope. This token is a super-admin override.</small>
        </details>
      </aside>
      <main>
        <ShellTopBar
          profile={profile}
          claims={claims}
          onLogout={logout}
          section={TAB_META[activeTab]?.section || `Console / ${activeLabel}`}
        />
        <section className="content aegis-content">
          {activeTab === "dashboard" && admin && <Dashboard />}
          {activeTab === "runs" && admin && <Runs />}
          {activeTab === "finops" && admin && <FinOps />}
          {activeTab === "policy" && admin && <PolicyExplorer />}
          {activeTab === "tenants" && admin && <Tenants />}
          {activeTab === "users" && admin && <Users />}
          {activeTab === "governance" && admin && <Governance />}
          {activeTab === "values" && <Values />}
          {activeTab === "audit" && admin && <Audit />}
          {activeTab === "mcp" && platformAdmin && <MCP />}
          {activeTab === "models" && platformAdmin && <Models />}
          {activeTab === "account" && <Account />}
        </section>
      </main>
    </div>
  );
}
