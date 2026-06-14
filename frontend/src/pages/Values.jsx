import React, { useEffect, useState, useRef } from "react";
import { api } from "../api/client.js";
import { keycloak } from "../auth/keycloak.js";

const cfg = window.AEGIS_CONFIG || {};
const API_BASE = cfg.API_BASE || "http://localhost:8080";

// Multipart upload helper (the api() wrapper assumes JSON, so we send the
// file separately while still attaching the Keycloak bearer token).
async function uploadValuesFile(file) {
  try { await keycloak.updateToken(30); } catch (_) { /* will 401 */ }
  const fd = new FormData();
  fd.append("file", file);
  const res = await fetch(`${API_BASE}/admin/values/extract`, {
    method: "POST",
    headers: { "Authorization": `Bearer ${keycloak.token}` },
    body: fd,
  });
  const text = await res.text();
  let data;
  try { data = text ? JSON.parse(text) : null; } catch (_) { data = text; }
  if (!res.ok) {
    const msg = (data && (data.error || data.detail)) || res.statusText || `HTTP ${res.status}`;
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return data;
}

/*
 * Values Documents page — narrative statements of values at every cascade scope.
 *
 * Scopes shown depend on the caller's role (via /admin/values/scopes):
 *   - platform-admin: organization + own tenant's department / team / role + individual
 *   - tenant-admin:   own tenant's department / team / role + individual
 *   - individual:     individual only
 */

const SCOPE_LABELS = {
  organization: "Organization",
  department:   "Department",
  team:         "Team",
  role:         "Role",
  individual:   "Individual",
};

export default function Values() {
  const [scopes, setScopes] = useState(null);
  const [tab, setTab] = useState("organization");
  const [docs, setDocs] = useState([]);
  const [editing, setEditing] = useState(null);  // doc object or {scope_type,...} for "new"
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");

  async function loadScopes() {
    try {
      const s = await api("/admin/values/scopes");
      setScopes(s);
      if (s.writable && Object.values(s.writable).some(Boolean)) {
        // pick the first scope the user can write to as default tab
        const first = ["organization", "department", "team", "role", "individual"]
          .find(k => s.writable[k]);
        if (first) setTab(first);
      }
    } catch (e) { setErr(String(e.message || e)); }
  }

  async function loadDocs() {
    setErr(""); setMsg("");
    try {
      const list = await api("/admin/values/documents");
      setDocs(list);
    } catch (e) { setErr(String(e.message || e)); }
  }

  useEffect(() => { loadScopes(); loadDocs(); }, []);

  const writable = scopes?.writable || {};
  const myTenant = scopes?.user_tenant_id;
  const myEmail  = scopes?.user_email;

  const filtered = docs.filter(d => d.scope_type === tab);

  function startNew() {
    const seed = { scope_type: tab, tenant_id: null, scope_id: null,
                   title: "", body_md: "" };
    if (tab === "department") { seed.tenant_id = myTenant; }
    if (tab === "team")       { seed.tenant_id = myTenant; seed.scope_id = ""; }
    if (tab === "role")       { seed.tenant_id = myTenant; seed.scope_id = ""; }
    if (tab === "individual") { seed.tenant_id = myTenant; seed.scope_id = myEmail; }
    setEditing(seed);
  }

  async function save() {
    setErr(""); setMsg("");
    const body = {
      scope_type: editing.scope_type,
      tenant_id:  editing.tenant_id || null,
      scope_id:   editing.scope_id || null,
      title:      editing.title,
      body_md:    editing.body_md,
    };
    try {
      if (editing.id) {
        await api(`/admin/values/documents/${editing.id}`, { method: "PUT", body });
      } else {
        await api("/admin/values/documents", { method: "POST", body });
      }
      setMsg("Saved.");
      setEditing(null);
      await loadDocs();
    } catch (e) { setErr(String(e.message || e)); }
  }

  async function del(d) {
    if (!confirm(`Delete "${d.title}"?`)) return;
    try {
      await api(`/admin/values/documents/${d.id}`, { method: "DELETE" });
      await loadDocs();
    } catch (e) { setErr(String(e.message || e)); }
  }

  if (!scopes) return <div className="card"><h2>Values</h2><p className="muted">Loading…</p></div>;

  return (
    <div className="card">
      <h2>Values Documents</h2>
      <p className="muted" style={{ marginTop: 0 }}>
        Narrative statements of values at each scope of the cascade — organization,
        department, team, role, individual. Who can edit what is enforced by the backend
        and reflected in the tabs below.
      </p>

      {err && <div className="error">{err}</div>}
      {msg && <div className="ok-msg">{msg}</div>}

      <div className="tabs" style={{ marginBottom: 16 }}>
        {["organization","department","team","role","individual"].map(k => (
          <button
            key={k}
            className={`tab ${tab === k ? "active" : ""}`}
            onClick={() => { setTab(k); setEditing(null); }}
          >
            {SCOPE_LABELS[k]}
            {writable[k] && <span style={{ marginLeft: 6, opacity: .6 }}>(editable)</span>}
          </button>
        ))}
      </div>

      {writable[tab] && !editing && (
        <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap" }}>
          <button onClick={startNew}>+ Add {SCOPE_LABELS[tab]} document</button>
          <LoadFromFileButton scope={tab} onLoaded={(extracted) => {
            const seed = { scope_type: tab, tenant_id: null, scope_id: null,
                           title: extracted.suggested_title || "",
                           body_md: extracted.body_md || "" };
            if (tab === "department") { seed.tenant_id = myTenant; }
            if (tab === "team")       { seed.tenant_id = myTenant; seed.scope_id = ""; }
            if (tab === "role")       { seed.tenant_id = myTenant; seed.scope_id = ""; }
            if (tab === "individual") { seed.tenant_id = myTenant; seed.scope_id = myEmail; }
            setEditing(seed);
            setMsg(`Loaded ${extracted.filename} (${extracted.size_bytes} bytes). Review and Save.`);
          }} onError={(m) => setErr(m)} />
        </div>
      )}

      {editing ? (
        <div style={{ background: "var(--bg-deep)", padding: 16, borderRadius: 8, border: "1px solid var(--line)" }}>
          <h3 style={{ marginTop: 0 }}>{editing.id ? "Edit" : "Create"} — {SCOPE_LABELS[editing.scope_type]}</h3>
          {(editing.scope_type !== "organization") && (
            <label>
              <span>Tenant (department)</span>
              <input value={editing.tenant_id || ""}
                     onChange={e => setEditing({...editing, tenant_id: e.target.value})}
                     placeholder="tenant-id" />
            </label>
          )}
          {(editing.scope_type === "team" || editing.scope_type === "role" || editing.scope_type === "individual") && (
            <label>
              <span>Scope id ({editing.scope_type === "team" ? "team_id" :
                              editing.scope_type === "role" ? "role_id" : "user email"})</span>
              <input value={editing.scope_id || ""}
                     onChange={e => setEditing({...editing, scope_id: e.target.value})} />
            </label>
          )}
          <label>
            <span>Title</span>
            <input value={editing.title}
                   onChange={e => setEditing({...editing, title: e.target.value})} />
          </label>
          <label>
            <span>Body (markdown)</span>
            <textarea rows={14} value={editing.body_md}
                      onChange={e => setEditing({...editing, body_md: e.target.value})} />
          </label>
          <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
            <button onClick={save}>Save</button>
            <LoadFromFileButton
              scope={editing.scope_type}
              onLoaded={(extracted) => {
                setEditing({ ...editing,
                  title:   editing.title || extracted.suggested_title || "",
                  body_md: extracted.body_md || editing.body_md });
                setMsg(`Loaded ${extracted.filename} into the editor.`);
              }}
              onError={(m) => setErr(m)} />
            <button className="ghost" onClick={() => setEditing(null)}>Cancel</button>
          </div>
        </div>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Title</th>
              <th>Tenant</th>
              <th>Scope id</th>
              <th>Author</th>
              <th>Updated</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 && (
              <tr><td colSpan="6" className="muted" style={{ padding: 22, textAlign: "center" }}>
                No {SCOPE_LABELS[tab].toLowerCase()} documents yet.
                {writable[tab] && " Click +New above to add one."}
              </td></tr>
            )}
            {filtered.map(d => (
              <tr key={d.id}>
                <td><b>{d.title}</b></td>
                <td><code>{d.tenant_id || "—"}</code></td>
                <td><code>{d.scope_id || "—"}</code></td>
                <td><small className="muted">{d.author_user}</small></td>
                <td><small className="muted">{(d.updated_at || "").slice(0, 16)}</small></td>
                <td style={{ whiteSpace: "nowrap" }}>
                  <button className="ghost" onClick={() => setEditing(d)}>Open</button>
                  {writable[tab] && (
                    <button className="ghost danger" style={{ marginLeft: 6 }}
                            onClick={() => del(d)}>Delete</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <p className="small" style={{ marginTop: 24 }}>
        Access matrix —
        platform-admin: <code>organization</code> + own department + team + role + individual;
        tenant-admin: own department + team + role + individual;
        anyone: <code>individual</code> only.
      </p>
    </div>
  );
}


// "Load from file" — wraps a hidden <input type=file> behind a styled button.
// Accepts .txt .md .docx .pdf, POSTs to /admin/values/extract, hands the
// extracted text + suggested title to the parent via onLoaded.
function LoadFromFileButton({ scope, onLoaded, onError }) {
  const inputRef = useRef(null);
  const [busy, setBusy] = useState(false);

  async function onPick(e) {
    const file = e.target.files && e.target.files[0];
    e.target.value = "";  // allow re-picking the same file
    if (!file) return;
    setBusy(true);
    try {
      const extracted = await uploadValuesFile(file);
      onLoaded && onLoaded(extracted);
    } catch (err) {
      onError && onError(String(err.message || err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <button
        type="button"
        className="ghost"
        disabled={busy}
        onClick={() => inputRef.current && inputRef.current.click()}
        title="Load text from .txt .md .docx .pdf — the editor pre-fills, Save writes through the same access matrix."
      >
        {busy ? "Loading…" : "Load from file"}
      </button>
      <input
        ref={inputRef}
        type="file"
        accept=".txt,.md,.markdown,.docx,.pdf"
        style={{ display: "none" }}
        onChange={onPick}
      />
    </>
  );
}
