import React, { useEffect, useState } from "react";
import { api } from "../api/client.js";

// Platform-admin only: pick the one global model that serves everyone. Model risk-tier gating
// was removed (v1.15.0) — ANY registered model can be set as the global default. Per-role
// governance (classification, skills, tools, budgets) still applies. Backed by GET/PUT /admin/model.
export default function Models() {
  const [data, setData] = useState({ models: [], active_model: "", source: "" });
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState("");

  async function load() {
    setErr("");
    try {
      const d = await api("/admin/model", { admin: true });
      setData(d);
    } catch (e) { setErr(String(e.message || e)); }
  }
  useEffect(() => { load(); }, []);

  async function setDefault(mid) {
    setErr(""); setMsg(""); setBusy(mid);
    try {
      const d = await api("/admin/model", { method: "PUT", admin: true, body: { model_id: mid } });
      setData(d);
      setMsg(`Global model is now ${d.active_model} — it serves every tenant and role.`);
    } catch (e) { setErr(String(e.message || e)); }
    finally { setBusy(""); }
  }

  const models = data.models || [];
  return (
    <div className="card">
      <h2>Models</h2>
      <p className="muted" style={{ marginTop: 0 }}>
        The platform admin picks one model that serves everyone. Default is{" "}
        <code>openai/gpt-4.1</code>. Any registered model can be made the global default — there is
        no model risk-tier restriction. Per-role governance (classification, skills, tools, budgets)
        still applies on top. The change takes effect on the next request, no redeploy.
      </p>
      {err && <div className="error">{err}</div>}
      {msg && <div className="ok-msg" style={{ marginBottom: 10 }}>{msg}</div>}
      <p>
        <b>Active model:</b> <code>{data.active_model}</code>{" "}
        <span className="role-badge">{data.source === "platform" ? "admin-selected" : "registry default"}</span>
      </p>
      <table>
        <thead>
          <tr><th>Model</th><th>Provider</th><th>Type</th><th>Tools</th><th></th></tr>
        </thead>
        <tbody>
          {models.map((m) => (
            <tr key={m.model_id} className={m.active ? "active-row" : ""}>
              <td>
                <b>{m.model_id}</b>{m.active ? " ✓" : ""}
                {(m.aliases && m.aliases.length > 0) && <><br /><small className="muted">{m.aliases.join(", ")}</small></>}
              </td>
              <td>{m.provider}</td>
              <td>{m.type}</td>
              <td>{m.supports_tools ? "yes" : "—"}</td>
              <td>
                {m.active
                  ? <span className="muted">current default</span>
                  : <button onClick={() => setDefault(m.model_id)} disabled={busy === m.model_id}>
                      {busy === m.model_id ? "Setting…" : "Set as default"}
                    </button>}
              </td>
            </tr>
          ))}
          {models.length === 0 && <tr><td colSpan="5" className="muted">No models registered.</td></tr>}
        </tbody>
      </table>
      <button className="ghost" onClick={load}>Refresh</button>
      <small className="muted" style={{ display: "block", marginTop: 8 }}>
        Hosted-model spend is capped by the per-role token/request budgets in Governance. Provide the
        provider API keys (OpenAI, NVIDIA, Anthropic) in <code>.env</code> at setup.
      </small>
    </div>
  );
}
