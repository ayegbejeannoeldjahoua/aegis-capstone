import React, { useEffect, useState } from "react";
import { api, canAdmin } from "../api/client.js";

export default function Approvals() {
  const [items, setItems] = useState([]);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");

  async function load() {
    setErr("");
    try { const r = await api("/admin/approvals", { admin: true }); setItems(r.approvals || []); }
    catch (e) { setErr(String(e.message || e)); }
  }
  useEffect(() => { if (canAdmin()) load(); }, []);

  async function act(id, verb) {
    setErr(""); setMsg("");
    try {
      await api(`/admin/approvals/${id}/${verb}`, { method: "POST", admin: true });
      setMsg(`${verb === "approve" ? "Approved" : "Rejected"} request #${id}.`);
      await load();
    } catch (e) { setErr(String(e.message || e)); }
  }

  if (!canAdmin()) return <div className="card warn">You don’t have administrative access for this view.</div>;

  return (
    <div className="card">
      <h2>Pending approvals</h2>
      {err && <div className="error">{err}</div>}
      {msg && <div className="ok-msg">{msg}</div>}
      <table>
        <thead><tr><th>ID</th><th>Action</th><th>Tenant</th><th>Requested by</th><th>Expires</th><th></th></tr></thead>
        <tbody>
          {items.map((a) => (
            <tr key={a.id}>
              <td>{a.id}</td><td>{a.action}</td><td>{a.tenant_id}</td><td>{a.requester}</td>
              <td><small className="muted">{a.expires_at}</small></td>
              <td>
                <button className="ghost" onClick={() => act(a.id, "approve")}>Approve</button>{" "}
                <button className="ghost danger" onClick={() => act(a.id, "reject")}>Reject</button>
              </td>
            </tr>
          ))}
          {items.length === 0 && <tr><td colSpan="6" className="muted">No pending approvals.</td></tr>}
        </tbody>
      </table>
      <button className="ghost" onClick={load}>Refresh</button>
      <small className="muted">Two-person rule: you cannot approve a request you made yourself.</small>
    </div>
  );
}
