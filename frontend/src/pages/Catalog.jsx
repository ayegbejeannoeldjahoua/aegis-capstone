import React, { useEffect, useState } from "react";
import { api } from "../api/client.js";

export default function Catalog() {
  const [skills, setSkills] = useState([]);
  const [tools, setTools] = useState([]);
  const [err, setErr] = useState("");

  async function load() {
    setErr("");
    try {
      const s = await api("/v1/skills"); setSkills(s.skills || []);
      const t = await api("/v1/tools"); setTools(t.tools || []);
    } catch (e) { setErr(String(e.message || e)); }
  }
  useEffect(() => { load(); }, []);

  return (
    <div className="grid2">
      <div className="card">
        <h2>Skills ({skills.length})</h2>
        {err && <div className="error">{err}</div>}
        <table>
          <thead><tr><th>Skill</th><th>Risk</th><th>Tools used</th><th>Signed</th></tr></thead>
          <tbody>
            {skills.map((s) => (
              <tr key={s.skill_id}>
                <td><b>{s.skill_id}</b><br /><small className="muted">{s.name}</small></td>
                <td>{s.risk_tier}</td>
                <td><small>{(s.tools || []).join(", ") || "—"}</small></td>
                <td>{s.signed ? "yes" : "no"}</td>
              </tr>
            ))}
            {skills.length === 0 && <tr><td colSpan="4" className="muted">No skills.</td></tr>}
          </tbody>
        </table>
        <button className="ghost" onClick={load}>Refresh</button>
      </div>
      <div className="card">
        <h2>Tools ({tools.length})</h2>
        <table>
          <thead><tr><th>Tool</th><th>Effect</th><th>Egress</th><th>PII</th></tr></thead>
          <tbody>
            {tools.map((t) => (
              <tr key={t.tool_id}>
                <td><b>{t.tool_id}</b></td><td>{t.side_effect}</td><td>{t.egress}</td><td>{t.pii}</td>
              </tr>
            ))}
            {tools.length === 0 && <tr><td colSpan="4" className="muted">No tools.</td></tr>}
          </tbody>
        </table>
        <small className="muted">Granting a skill/tool to a role is done in Governance; invocation is gated by the PDP.</small>
      </div>
    </div>
  );
}
