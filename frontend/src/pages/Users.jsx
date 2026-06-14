import React, { useEffect, useState } from "react";
import { api, canAdmin } from "../api/client.js";

const EMPTY = { email: "", tenant_id: "", team_id: "research", role_id: "", create_login: false, password: "" };

export default function Users() {
  const [users, setUsers] = useState([]);
  const [tenants, setTenants] = useState([]);
  const [roles, setRoles] = useState([]);
  const [teams, setTeams] = useState([]);
  const [form, setForm] = useState(EMPTY);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [resetFor, setResetFor] = useState(null);
  const [newPw, setNewPw] = useState("");
  const [resetMsg, setResetMsg] = useState("");
  const [provFor, setProvFor] = useState(null);
  const [provPw, setProvPw] = useState("");
  const [editId, setEditId] = useState(null);
  const [editForm, setEditForm] = useState({ tenant_id: "", team_id: "", role_id: "" });
  const [editTeams, setEditTeams] = useState([]);
  const [editRoles, setEditRoles] = useState([]);

  async function load() {
    setErr("");
    try {
      const u = await api("/admin/users", { admin: true });
      setUsers(u.users || []);
      const t = await api("/admin/tenants", { admin: true });
      setTenants(t.tenants || []);
    } catch (e) { setErr(String(e.message || e)); }
  }
  useEffect(() => { if (canAdmin()) load(); }, []);

  async function pickTenant(tid) {
    setForm((f) => ({ ...f, tenant_id: tid, role_id: "", team_id: "" }));
    if (!tid) { setRoles([]); setTeams([]); return; }
    try {
      const d = await api(`/admin/tenants/${tid}`, { admin: true });
      setRoles(d.roles || []); setTeams(d.teams || []);
      setForm((f) => ({ ...f, team_id: (d.teams[0] && d.teams[0].team_id) || "research" }));
    } catch { setRoles([]); setTeams([]); }
  }

  async function create(e) {
    e.preventDefault(); setBusy(true); setErr("");
    try { await api("/admin/users", { method: "POST", admin: true, body: form }); setForm(EMPTY); setRoles([]); await load(); }
    catch (e) { setErr(String(e.message || e)); }
    finally { setBusy(false); }
  }

  async function del(id) {
    if (!window.confirm("Remove this assignment?")) return;
    try { await api(`/admin/users/${id}`, { method: "DELETE", admin: true }); await load(); }
    catch (e) { setErr(String(e.message || e)); }
  }

  function openReset(email) { setResetFor(email); setProvFor(null); setNewPw(""); setErr(""); setResetMsg(""); }

  async function doReset(e) {
    e.preventDefault(); setErr(""); setResetMsg("");
    if (newPw.length < 8) { setErr("New password must be at least 8 characters."); return; }
    try {
      await api("/admin/users/reset-password", { method: "POST", admin: true, body: { email: resetFor, new_password: newPw } });
      setResetMsg(`Password reset for ${resetFor}.`); setResetFor(null); setNewPw("");
    } catch (e) { setErr(String(e.message || e)); }
  }

  function openProvision(email) { setProvFor(email); setResetFor(null); setEditId(null); setProvPw(""); setErr(""); setResetMsg(""); }

  async function doProvision(e) {
    e.preventDefault(); setErr(""); setResetMsg("");
    if (provPw.length < 8) { setErr("Password must be at least 8 characters."); return; }
    try {
      const r = await api("/admin/users/provision-login", { method: "POST", admin: true, body: { email: provFor, password: provPw } });
      const created = r && r.login && r.login.created;
      const rebound = r && r.rebound ? " — sub binding reset, they can sign in fresh" : "";
      setResetMsg(`Login ${created ? "created" : "refreshed"} for ${provFor}${rebound}.`);
      setProvFor(null); setProvPw(""); await load();
    } catch (e) { setErr(String(e.message || e)); }
  }

  async function openEdit(u) {
    setErr(""); setResetFor(null); setProvFor(null); setEditId(u.assignment_id);
    try {
      const d = await api(`/admin/tenants/${u.tenant_id}`, { admin: true });
      setEditTeams(d.teams || []); setEditRoles(d.roles || []);
      setEditForm({ tenant_id: u.tenant_id, team_id: u.team_id, role_id: u.role_id });
    } catch (e) { setErr(String(e.message || e)); }
  }

  async function editPickTenant(tid) {
    setEditForm((f) => ({ ...f, tenant_id: tid, team_id: "", role_id: "" }));
    if (!tid) { setEditTeams([]); setEditRoles([]); return; }
    try {
      const d = await api(`/admin/tenants/${tid}`, { admin: true });
      setEditTeams(d.teams || []); setEditRoles(d.roles || []);
      setEditForm((f) => ({ ...f, team_id: (d.teams[0] && d.teams[0].team_id) || "", role_id: (d.roles[0] && d.roles[0].role_id) || "" }));
    } catch { setEditTeams([]); setEditRoles([]); }
  }

  async function saveEdit(e) {
    e.preventDefault(); setErr("");
    try {
      await api(`/admin/users/${editId}`, { method: "PUT", admin: true, body: editForm });
      setEditId(null); await load();
    } catch (e) { setErr(String(e.message || e)); }
  }

  if (!canAdmin()) return <div className="card warn">You don\u2019t have administrative access for this view.</div>;

  return (
    <div className="grid2">
      <div className="card">
        <h2>Users &amp; assignments</h2>
        {err && <div className="error">{err}</div>}
        <table>
          <thead><tr><th>Email</th><th>Tenant</th><th>Team</th><th>Role</th><th>Bound</th><th></th></tr></thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.assignment_id}>
                <td>{u.user_email}</td><td>{u.tenant_id}</td><td>{u.team_id}</td><td>{u.role_id}</td>
                <td>{u.bound ? "yes" : "—"}</td>
                <td>
                  <button className="ghost" onClick={() => openEdit(u)}>Move/Edit</button>{" "}
                  <button className="ghost" onClick={() => openReset(u.user_email)}>Reset pw</button>{" "}
                  <button className="ghost" onClick={() => openProvision(u.user_email)}>Provision login</button>{" "}
                  <button className="ghost danger" onClick={() => del(u.assignment_id)}>Delete</button>
                </td>
              </tr>
            ))}
            {users.length === 0 && <tr><td colSpan="6" className="muted">No assignments yet.</td></tr>}
          </tbody>
        </table>
        <button className="ghost" onClick={load}>Refresh</button>
        {resetMsg && <div className="ok-msg" style={{ marginTop: 10 }}>{resetMsg}</div>}
        {resetFor && (
          <form className="reset-pw" onSubmit={doReset}>
            <strong>Reset password for {resetFor}</strong>
            <input type="password" value={newPw} placeholder="New password (min 8)" autoComplete="new-password"
                   onChange={(e) => setNewPw(e.target.value)} />
            <button type="submit">Set password</button>
            <button type="button" className="ghost" onClick={() => setResetFor(null)}>Cancel</button>
          </form>
        )}
        {provFor && (
          <form className="reset-pw" onSubmit={doProvision}>
            <strong>(Re)provision login for {provFor}</strong>
            <p className="muted" style={{ margin: "4px 0" }}>Creates or refreshes the Keycloak login and resets the binding, so an account stranded by a Keycloak reset can sign in again.</p>
            <input type="password" value={provPw} placeholder="Login password (min 8)" autoComplete="new-password"
                   onChange={(e) => setProvPw(e.target.value)} />
            <button type="submit">Provision login</button>
            <button type="button" className="ghost" onClick={() => setProvFor(null)}>Cancel</button>
          </form>
        )}
        {editId && (
          <form className="reset-pw" onSubmit={saveEdit}>
            <strong>Move / edit assignment</strong>
            <select value={editForm.tenant_id} onChange={(e) => editPickTenant(e.target.value)}>
              {tenants.map((t) => <option key={t.tenant_id} value={t.tenant_id}>{t.tenant_id}</option>)}
            </select>
            <select value={editForm.team_id} onChange={(e) => setEditForm({ ...editForm, team_id: e.target.value })}>
              {editTeams.map((t) => <option key={t.team_id} value={t.team_id}>{t.team_id}</option>)}
            </select>
            <select value={editForm.role_id} required onChange={(e) => setEditForm({ ...editForm, role_id: e.target.value })}>
              <option value="">role…</option>
              {editRoles.map((r) => <option key={r.role_id} value={r.role_id}>{r.role_id}</option>)}
            </select>
            <button type="submit">Save</button>
            <button type="button" className="ghost" onClick={() => setEditId(null)}>Cancel</button>
          </form>
        )}
      </div>
      <div className="card">
        <h2>Assign a user</h2>
        <form onSubmit={create}>
          <label>Email
            <input value={form.email} placeholder="dana@gamma-corp.example" required
                   onChange={(e) => setForm({ ...form, email: e.target.value })} />
          </label>
          <label>Tenant
            <select value={form.tenant_id} required onChange={(e) => pickTenant(e.target.value)}>
              <option value="">Select…</option>
              {tenants.map((t) => <option key={t.tenant_id} value={t.tenant_id}>{t.tenant_id}</option>)}
            </select>
          </label>
          <label>Team
            <select value={form.team_id} onChange={(e) => setForm({ ...form, team_id: e.target.value })}>
              {teams.length === 0 && <option value="research">research</option>}
              {teams.map((t) => <option key={t.team_id} value={t.team_id}>{t.team_id}</option>)}
            </select>
          </label>
          <label>Role
            <select value={form.role_id} required onChange={(e) => setForm({ ...form, role_id: e.target.value })}>
              <option value="">Select…</option>
              {roles.map((r) => <option key={r.role_id} value={r.role_id}>{r.role_id}</option>)}
            </select>
          </label>
          <label className="row">
            <input type="checkbox" checked={form.create_login}
                   onChange={(e) => setForm({ ...form, create_login: e.target.checked })} />
            Also create a Keycloak login
          </label>
          {form.create_login && (
            <label>Initial password
              <input type="password" value={form.password}
                     onChange={(e) => setForm({ ...form, password: e.target.value })} />
            </label>
          )}
          <button type="submit" disabled={busy}>{busy ? "Saving…" : "Create assignment"}</button>
        </form>
        <small>The DB assignment governs access; the optional Keycloak login lets the person authenticate.</small>
      </div>
    </div>
  );
}
