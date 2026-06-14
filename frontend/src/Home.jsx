import React from "react";

export default function Home({ profile, onLogout, go }) {
  return (
    <div className="home">
      <header className="topbar">
        <div className="brand">Aegis<span>AI Governance Platform</span></div>
        <div className="who">
          {profile ? profile.email : "user"}
          {profile && <span className="role-badge">{profile.role} · {profile.admin_scope}</span>}
          <button className="ghost" onClick={onLogout}>Log out</button>
        </div>
      </header>
      <section className="home-cards">
        <button className="home-card" onClick={() => go("chat")}>
          <h2>Chat</h2>
          <p>Ask the governed assistant. Every request is policy-checked, model-routed, budgeted and audited under your role.</p>
          <span className="cta">Open chat →</span>
        </button>
        <button className="home-card" onClick={() => go("console")}>
          <h2>Admin &amp; Governance Console</h2>
          <p>Tenants, teams, roles &amp; capabilities, users, approvals, the skills/tools catalog and the test console.</p>
          <span className="cta">Open console →</span>
        </button>
      </section>
    </div>
  );
}
