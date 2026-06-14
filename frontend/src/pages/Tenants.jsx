import React, { useEffect, useState } from "react";
import { api, canAdmin } from "../api/client.js";

export default function Tenants() {
  const [tenants, setTenants] = useState([]);
  const [detail, setDetail] = useState(null);
  const [templates, setTemplates] = useState([]);
  const [err, setErr] = useState("");
  const [form, setForm] = useState({ tenant_id: "", display_name: "", region: "AC1" });
  const [roleForm, setRoleForm] = useState({ role_id: "", team_id: "research", template_id: "viewer" });
  const [teamForm, setTeamForm] = useState({ team_id: "", display_name: "" });
  const [busy, setBusy] = useState(false);

  async function load() {
    setErr("");
    try {
      const r = await api("/admin/tenants", { admin: true });
      setTenants(r.tenants || []);
      const t = await api("/admin/templates", { admin: true });
      setTemplates(t.templates || []);
    } catch (e) { setErr(String(e.message || e)); }
  }
  useEffect(() => { if (canAdmin()) load(); }, []);

  async function create(e) {
    e.preventDefault(); setBusy(true); setErr("");
    try {
      await api("/admin/tenants", { method: "POST", admin: true, body: form });
      setForm({ tenant_id: "", display_name: "", region: "AC1" });
      await load();
    } catch (e) { setErr(String(e.message || e)); }
    finally { setBusy(false); }
  }

  async function open(id) {
    setErr("");
    try {
      const d = await api(`/admin/tenants/${id}`, { admin: true });
      setDetail(d);
      setRoleForm((rf) => ({ ...rf, team_id: (d.teams[0] && d.teams[0].team_id) || "research" }));
    } catch (e) { setErr(String(e.message || e)); }
  }

  async function addRole(e) {
    e.preventDefault(); setErr("");
    try {
      await api(`/admin/tenants/${detail.tenant_id}/roles`, { method: "POST", admin: true, body: roleForm });
      setRoleForm({ role_id: "", team_id: "research", template_id: "viewer" });
      await open(detail.tenant_id); await load();
    } catch (e) { setErr(String(e.message || e)); }
  }

  async function delTenant() {
    const id = detail.tenant_id;
    const typed = window.prompt(`This permanently deletes tenant "${id}" and its teams, roles, memories and assignments (the audit ledger is retained). Type ${id} to confirm:`);
    if (typed !== id) return;
    setErr("");
    try {
      await api(`/admin/tenants/${id}`, { method: "DELETE", admin: true, body: { confirm: id } });
      setDetail(null);
      await load();
    } catch (e) { setErr(String(e.message || e)); }
  }

  async function delRole(roleId) {
    if (!window.confirm(`Delete role ${roleId}?`)) return;
    try { await api(`/admin/tenants/${detail.tenant_id}/roles/${roleId}`, { method: "DELETE", admin: true }); await open(detail.tenant_id); await load(); }
    catch (e) { setErr(String(e.message || e)); }
  }

  async function addTeam(e) {
    e.preventDefault(); setErr("");
    try {
      await api(`/admin/tenants/${detail.tenant_id}/teams`, { method: "POST", admin: true, body: teamForm });
      setTeamForm({ team_id: "", display_name: "" });
      await open(detail.tenant_id); await load();
    } catch (e) { setErr(String(e.message || e)); }
  }

  async function delTeam(teamId) {
    if (!window.confirm(`Delete team ${teamId}? (it must have no roles)`)) return;
    try { await api(`/admin/tenants/${detail.tenant_id}/teams/${teamId}`, { method: "DELETE", admin: true }); await open(detail.tenant_id); await load(); }
    catch (e) { setErr(String(e.message || e)); }
  }

  if (!canAdmin()) return <div className="card warn">You don\u2019t have administrative access for this view.</div>;

  return (
    <div className="grid2">
      <div className="card">
        <h2>Tenants</h2>
        {err && <div className="error">{err}</div>}
        <table>
          <thead><tr><th>ID</th><th>Name</th><th>Region</th><th>Roles</th></tr></thead>
          <tbody>
            {tenants.map((t) => (
              <tr key={t.tenant_id} className="clickable" onClick={() => open(t.tenant_id)}>
                <td>{t.tenant_id}</td><td>{t.display_name}</td><td>{t.region}</td><td>{t.role_count}</td>
              </tr>
            ))}
            {tenants.length === 0 && <tr><td colSpan="4" className="muted">No tenants yet.</td></tr>}
          </tbody>
        </table>
        <button className="ghost" onClick={load}>Refresh</button>

        <h2 style={{ marginTop: 18 }}>New tenant</h2>
        <form onSubmit={create}>
          <label>Tenant ID<input value={form.tenant_id} placeholder="gamma-corp" required
                                  onChange={(e) => setForm({ ...form, tenant_id: e.target.value })} /></label>
          <label>Display name<input value={form.display_name} placeholder="Gamma Corp" required
                                     onChange={(e) => setForm({ ...form, display_name: e.target.value })} /></label>
          <label>Region<input value={form.region} onChange={(e) => setForm({ ...form, region: e.target.value })} /></label>
          <button type="submit" disabled={busy}>{busy ? "Creating…" : "Create tenant"}</button>
        </form>
      </div>

      <div className="card">
        <h2>Tenant detail</h2>
        {!detail && <small className="muted">Select a tenant to view and manage its roles.</small>}
        {detail && (
          <div>
            <div className="detail-head"><h3>{detail.tenant_id}</h3><button className="ghost danger sm" onClick={delTenant}>Delete tenant</button></div>
            <h3>Teams</h3>
            <ul className="roles">
              {detail.teams.map((t) => (
                <li key={t.team_id}>
                  <div><b>{t.team_id}</b> <span className="muted">{t.display_name}</span>{" "}
                    <button className="ghost danger sm" onClick={() => delTeam(t.team_id)}>delete</button></div>
                </li>
              ))}
              {detail.teams.length === 0 && <li className="muted">No teams.</li>}
            </ul>
            <form onSubmit={addTeam} className="inline">
              <input value={teamForm.team_id} placeholder="team id (e.g. finance)" required
                     onChange={(e) => setTeamForm({ ...teamForm, team_id: e.target.value })} />
              <input value={teamForm.display_name} placeholder="display name (optional)"
                     onChange={(e) => setTeamForm({ ...teamForm, display_name: e.target.value })} />
              <button type="submit">Add team</button>
            </form>
            <ul className="roles">
              {detail.roles.map((r) => (
                <li key={r.role_id}>
                  <div><b>{r.role_id}</b> <button className="ghost danger sm" onClick={() => delRole(r.role_id)}>delete</button></div>
                  <small>skills: {(r.capabilities.skills || []).join(", ") || "none"}; writes: {(r.capabilities.writable_namespaces || []).join(", ") || "none"}</small>
                </li>
              ))}
            </ul>
            <h3>Add role from template</h3>
            <form onSubmit={addRole} className="inline">
              <input value={roleForm.role_id} placeholder="role id (e.g. finance-analyst)" required
                     onChange={(e) => setRoleForm({ ...roleForm, role_id: e.target.value })} />
              <select value={roleForm.team_id} onChange={(e) => setRoleForm({ ...roleForm, team_id: e.target.value })}>
                {detail.teams.map((t) => <option key={t.team_id} value={t.team_id}>{t.team_id}</option>)}
              </select>
              <select value={roleForm.template_id} onChange={(e) => setRoleForm({ ...roleForm, template_id: e.target.value })}>
                {templates.map((t) => <option key={t.template_id} value={t.template_id}>{t.template_id}</option>)}
              </select>
              <button type="submit">Add</button>
            </form>
          </div>
        )}
      </div>
    </div>
  );
}
