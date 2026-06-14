import React, { useEffect, useState } from "react";
import { api } from "../api/client.js";

const DEFAULT_FORM = {
  server_id: "", display_name: "", version: "1.0.0",
  public_key: "", signature: "",
  tools_json: '[{"tool_id":"example_search","description":"...","parameters":{}}]',
  command: "python", args_csv: "-m, my_module.server",
  env_json: "{}", cwd: "/app",
  // v1.23.2 Discover-from-PyPI helper fields
  pypi_package: "", module_path: "",
  // v1.23.3 -- track whether user manually edited these so smart-defaults
  // keep re-deriving from server_id until they explicitly type something.
  _pypi_touched: false, _module_touched: false,
  // v1.23.6 Discover-from-Docker fields
  docker_image: "", _docker_touched: false,
};

// Convention used by most MCP PyPI packages: e.g.
//   server_id "paper-search" -> pypi "paper-search-mcp",
//                                module "paper_search_mcp.server"
function defaultsFromServerId(sid) {
  if (!sid) return { pypi_package: "", module_path: "" };
  const dashed = sid.endsWith("-mcp") ? sid : sid + "-mcp";
  const underscored = dashed.replace(/-/g, "_");
  return { pypi_package: dashed, module_path: underscored + ".server" };
}

// v1.22 MCP tab. Platform admins register servers; the second platform admin
// approves via the Approvals tab. Tools become callable only after approval.
export default function MCP() {
  const [servers, setServers] = useState([]);
  const [form, setForm] = useState(DEFAULT_FORM);
  const [busy, setBusy] = useState(false);
  const [showAdd, setShowAdd] = useState(false);
  const [msg, setMsg] = useState("");

  async function load() {
    try { const r = await api("/admin/mcp/servers"); setServers(r.items || []); }
    catch (e) { setMsg(String(e.message || e)); }
  }
  useEffect(() => { load(); }, []);

  async function submitForm() {
    setBusy(true); setMsg("");
    try {
      const tools = JSON.parse(form.tools_json || "[]");
      const args = (form.args_csv || "").split(",").map((s) => s.trim()).filter(Boolean);
      const env = JSON.parse(form.env_json || "{}");
      const body = {
        server_id: form.server_id, display_name: form.display_name, version: form.version,
        public_key: form.public_key, signature: form.signature, tools,
        command: form.command, args, env, cwd: form.cwd,
      };
      const r = await api("/admin/mcp/register", { method: "POST", body });
      setMsg(`queued (pending_id=${r.pending_id}, hash=${(r.manifest_hash || "").slice(0, 12)}…)`);
      setForm(DEFAULT_FORM); setShowAdd(false); load();
    } catch (e) {
      setMsg(`refused: ${String(e.message || e)}`);
    } finally { setBusy(false); }
  }

  async function quarantine(server_id) {
    if (!window.confirm(`Quarantine ${server_id}? Existing tool calls will be blocked.`)) return;
    setBusy(true); setMsg("");
    try { await api(`/admin/mcp/${server_id}/quarantine`, { method: "POST" }); load(); }
    catch (e) { setMsg(String(e.message || e)); }
    finally { setBusy(false); }
  }

  // v1.23.5 -- DELETE the server outright. Works on any status (pending, approved, quarantined).
  async function removeServer(server_id, status) {
    if (!window.confirm(`Remove ${server_id} (${status})? This deletes the registration and all its tools. Cannot be undone.`)) return;
    setBusy(true); setMsg("");
    try {
      const r = await api(`/admin/mcp/${server_id}`, { method: "DELETE" });
      setMsg(`removed ${server_id} (prior status: ${r.prior_status})`);
      load();
    } catch (e) { setMsg(String(e.message || e)); }
    finally { setBusy(false); }
  }

  return (
    <div>
      <h2>MCP gateway <small className="muted">platform-only</small></h2>
      <p className="muted">Every server must arrive with a signed manifest. Tool descriptions are
        injection-scanned at registration; if the signature verifies and the scan passes, the server is
        auto-approved and its tools become callable. Set <code>AEGIS_MCP_REQUIRE_DUAL_CONTROL=true</code>
        in <code>.env</code> to require a second platform admin to approve via the Approvals tab.
        Each tool id is namespaced <code>server_id/tool_id</code>.</p>

      {msg && <div className="ok-msg" style={{ marginBottom: 8 }}>{msg}</div>}

      <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
        <button type="button" disabled={busy}
                onClick={async () => {
                  setBusy(true); setMsg("");
                  try {
                    const r = await api("/admin/mcp/register-demo", { method: "POST" });
                    setMsg(`queued demo (pending_id=${r.pending_id})`); load();
                  } catch (e) { setMsg(`refused: ${String(e.message || e)}`); }
                  finally { setBusy(false); }
                }}>
          Register stdio demo (demo-mcp)
        </button>
        <button type="button" className="ghost" onClick={() => setShowAdd(!showAdd)}>
          {showAdd ? "Cancel" : "+ Register MCP server"}
        </button>
        <button type="button" className="ghost" onClick={load}>Refresh</button>
      </div>

      {showAdd && (
        <div className="add-form" style={{ display: "grid", gap: 6, maxWidth: 760, marginBottom: 12 }}>
          <label>server_id<input value={form.server_id}
            onChange={(e) => {
              const v = e.target.value;
              const d = defaultsFromServerId(v);
              setForm({ ...form, server_id: v,
                pypi_package: form._pypi_touched   ? form.pypi_package : d.pypi_package,
                module_path:  form._module_touched ? form.module_path  : d.module_path,
                docker_image: form._docker_touched ? form.docker_image : (v ? `mcp/${v}` : ""),
                display_name: form.display_name || (v ? v.charAt(0).toUpperCase()+v.slice(1).replace(/-/g," ") : ""),
              });
            }} /></label>
          <fieldset className="discover-fs" style={{ border: "1px solid #e4e4e4", padding: 8, borderRadius: 6, marginTop: 4 }}>
            <legend><small>Discover from PyPI <span className="muted">(v1.23.2)</span></small></legend>
            <label>pypi_package<input value={form.pypi_package}
              placeholder="paper-search-mcp"
              onChange={(e) => setForm({ ...form, pypi_package: e.target.value, _pypi_touched: true })} /></label>
            <label>module_path<input value={form.module_path}
              placeholder="paper_search_mcp.server"
              onChange={(e) => setForm({ ...form, module_path: e.target.value, _module_touched: true })} /></label>
            <button type="button" disabled={busy || !form.pypi_package || !form.module_path}
                    onClick={async () => {
                      setBusy(true); setMsg("");
                      try {
                        const r = await api("/admin/mcp/discover", {
                          method: "POST",
                          body: { pypi_package: form.pypi_package, module_path: form.module_path },
                        });
                        setForm({ ...form,
                          public_key: r.public_key,
                          signature: r.signature,
                          tools_json: JSON.stringify(r.tools),
                          command: r.suggested_command,
                          args_csv: (r.suggested_args || []).join(", "),
                          cwd: r.suggested_cwd || form.cwd,
                        });
                        setMsg(`discovered ${r.tools_count} tools -- review below and click Stage registration`);
                      } catch (e) { setMsg(`discover failed: ${String(e.message || e)}`); }
                      finally { setBusy(false); }
                    }}>Discover</button>
            <small className="muted" style={{ display: "block", marginTop: 4 }}>
              Runs <code>pip install &lt;pypi_package&gt;</code> + handshake + sign in the api container,
              then fills the rest of the form below for your review.
            </small>
          </fieldset>
          <fieldset className="discover-fs" style={{ border: "1px solid #e4e4e4", padding: 8, borderRadius: 6, marginTop: 4 }}>
            <legend><small>Discover from Docker image <span className="muted">(v1.23.6)</span></small></legend>
            <label>docker_image<input value={form.docker_image}
              placeholder="mcp/aws-core"
              onChange={(e) => setForm({ ...form, docker_image: e.target.value, _docker_touched: true })} /></label>
            <button type="button" disabled={busy || !form.docker_image}
                    onClick={async () => {
                      setBusy(true); setMsg("");
                      try {
                        const r = await api("/admin/mcp/discover-docker", {
                          method: "POST",
                          body: { docker_image: form.docker_image, extra_env: {} },
                        });
                        setForm({ ...form,
                          public_key: r.public_key,
                          signature: r.signature,
                          tools_json: JSON.stringify(r.tools),
                          command: r.suggested_command,
                          args_csv: (r.suggested_args || []).join(", "),
                          cwd: r.suggested_cwd || form.cwd,
                        });
                        setMsg(`discovered ${r.tools_count} tools from ${form.docker_image} -- review below and click Stage registration`);
                      } catch (e) { setMsg(`docker discover failed: ${String(e.message || e)}`); }
                      finally { setBusy(false); }
                    }}>Discover (Docker)</button>
            <small className="muted" style={{ display: "block", marginTop: 4 }}>
              Pulls the image + runs <code>docker run -i --rm &lt;docker_image&gt;</code> for the MCP handshake.
              Works for any server on the Docker MCP Hub (mcp/* images).
            </small>
          </fieldset>
          <label>display_name<input value={form.display_name}
            onChange={(e) => setForm({ ...form, display_name: e.target.value })} /></label>
          <label>version<input value={form.version}
            onChange={(e) => setForm({ ...form, version: e.target.value })} /></label>
          <label>public_key (base64)<input value={form.public_key}
            onChange={(e) => setForm({ ...form, public_key: e.target.value })} /></label>
          <label>signature (base64)<input value={form.signature}
            onChange={(e) => setForm({ ...form, signature: e.target.value })} /></label>
          <label>tools (JSON array of ToolSpec)
            <textarea rows={4} value={form.tools_json}
              onChange={(e) => setForm({ ...form, tools_json: e.target.value })} /></label>
          <hr/>
          <label>command<input value={form.command}
            onChange={(e) => setForm({ ...form, command: e.target.value })} /></label>
          <label>args (comma-separated)<input value={form.args_csv}
            placeholder="-m, my_company.mcp_server"
            onChange={(e) => setForm({ ...form, args_csv: e.target.value })} /></label>
          <label>env (JSON object)<input value={form.env_json}
            onChange={(e) => setForm({ ...form, env_json: e.target.value })} /></label>
          <label>cwd<input value={form.cwd}
            onChange={(e) => setForm({ ...form, cwd: e.target.value })} /></label>
          <button type="button" disabled={busy} onClick={submitForm}>Stage registration</button>
        </div>
      )}

      <table style={{ marginTop: 10 }}>
        <thead><tr><th>Server</th><th>Version</th><th>Status</th><th>Tools</th><th>Hash</th><th></th></tr></thead>
        <tbody>
          {servers.length === 0 && <tr><td colSpan="6" className="muted">No MCP servers registered.</td></tr>}
          {servers.map((s) => (
            <tr key={s.server_id}>
              <td><b>{s.server_id}</b><br/><small className="muted">{s.display_name}</small></td>
              <td><code>{s.version}</code></td>
              <td><span className="role-badge">{s.status}</span></td>
              <td>{(s.tools || []).map((t) => (
                <div key={t.tool_id}>
                  <small><code>{s.server_id}/{t.tool_id}</code>
                    {t.scan_action !== "allow" && <span className="error"> ({t.scan_action})</span>}
                  </small>
                </div>
              ))}</td>
              <td><small><code>{(s.manifest_hash || "").slice(0, 12)}…</code></small></td>
              <td>
                <button type="button" className="ghost sm" onClick={() => removeServer(s.server_id, s.status)} disabled={busy}
                        style={{ color: "#b32525" }}>
                  Remove
                </button>
                {s.status === "approved" && (
                  <button type="button" className="ghost sm" onClick={() => quarantine(s.server_id)} disabled={busy}
                          style={{ marginLeft: 4 }}>
                    Quarantine
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
