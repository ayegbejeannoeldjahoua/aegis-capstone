import React from "react";
import {
  Activity,
  ChevronRight,
  DollarSign,
  FileText,
  Gavel,
  LayoutDashboard,
  LogOut,
  MessageSquare,
  Shield,
  User,
} from "lucide-react";
import { AegisBadge, AegisButton, AegisLogo } from "./components/figma/AegisPrimitives.jsx";
import ThemeToggle from "./theme/ThemeToggle.jsx";

const HOME_CARDS = [
  {
    title: "Chat",
    meta: "governed assistant",
    icon: MessageSquare,
    action: (go) => go("chat"),
    cta: "Open chat",
  },
  {
    title: "Console",
    meta: "governance workspace",
    icon: Shield,
    action: (go) => go("console"),
    cta: "Open console",
  },
  {
    title: "Dashboard",
    meta: "requests, allow rate, health",
    icon: LayoutDashboard,
    action: (go) => go("console", "dashboard"),
    cta: "View dashboard",
  },
  {
    title: "FinOps",
    meta: "spend, budgets, denials",
    icon: DollarSign,
    action: (go) => go("console", "finops"),
    cta: "View FinOps",
  },
  {
    title: "Governance & Policy",
    meta: "capabilities and policy matrix",
    icon: Gavel,
    action: (go) => go("console", "governance"),
    cta: "Open governance",
  },
  {
    title: "Audit",
    meta: "trace and decision log",
    icon: FileText,
    action: (go) => go("console", "audit"),
    cta: "Open audit",
  },
];

export default function Home({ profile, onLogout, go }) {
  const role = profile?.role || "user";
  const tenant = profile?.tenant_id || "tenant pending";
  const scope = profile?.admin_scope || "none";

  return (
    <div className="home aegis-home">
      <header className="aegis-topbar">
        <div className="aegis-topbar-left">
          <AegisLogo compact />
          <span className="aegis-topbar-section">Home</span>
        </div>
        <div className="aegis-topbar-right">
          <ThemeToggle />
          <span className="aegis-user-email">{profile ? profile.email : "user"}</span>
          <AegisBadge>{role}<span>{scope}</span></AegisBadge>
          <AegisButton variant="ghost" icon={LogOut} onClick={onLogout}>Log out</AegisButton>
        </div>
      </header>

      <main className="aegis-home-main">
        <section className="aegis-home-hero" aria-labelledby="home-title">
          <div>
            <div className="aegis-eyebrow">Signed in</div>
            <h1 id="home-title">Aegis</h1>
            <p>AI Governance Platform</p>
          </div>
          <div className="aegis-profile-panel">
            <div className="aegis-profile-avatar"><User size={16} /></div>
            <div>
              <strong>{profile ? profile.email : "user"}</strong>
              <span>{role} · {tenant}</span>
            </div>
            <AegisBadge tone={scope === "platform" ? "blue" : "green"}>{scope}</AegisBadge>
          </div>
        </section>

        <section className="aegis-home-grid" aria-label="Aegis areas">
          {HOME_CARDS.map((card) => {
            const Icon = card.icon;
            return (
              <button key={card.title} className="aegis-home-card" onClick={() => card.action(go)} type="button">
                <div className="aegis-home-card-icon"><Icon size={16} /></div>
                <div>
                  <h2>{card.title}</h2>
                  <p>{card.meta}</p>
                </div>
                <span className="aegis-home-card-cta">{card.cta}<ChevronRight size={12} /></span>
              </button>
            );
          })}
        </section>

        <section className="aegis-home-strip" aria-label="Session metadata">
          <span><Activity size={12} /> role {role}</span>
          <span>tenant {tenant}</span>
          <span>admin scope {scope}</span>
        </section>
      </main>
    </div>
  );
}
