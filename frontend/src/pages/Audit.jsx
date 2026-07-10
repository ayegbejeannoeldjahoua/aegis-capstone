import React, { useEffect, useState } from "react";
import { api, canAdmin } from "../api/client.js";

function currentMonthKey() {
  return new Date().toISOString().slice(0, 7);
}

export default function Audit() {
  const [events, setEvents] = useState([]);
  const [scope, setScope] = useState("");
  const [limit, setLimit] = useState(50);
  const [month, setMonth] = useState(currentMonthKey());
  const [trace, setTrace] = useState(null);
  const [traceId, setTraceId] = useState("");
  const [verify, setVerify] = useState(null);
  const [err, setErr] = useState("");

  async function load() {
    setErr(""); setTrace(null); setTraceId(""); setVerify(null);
    try {
      const qs = new URLSearchParams({ limit: String(limit), month });
      const r = await api(`/admin/audit/last?${qs.toString()}`, { admin: true });
      setEvents(r.events || []); setScope(r.scope || "");
    } catch (e) { setErr(String(e.message || e)); }
  }
  useEffect(() => { if (canAdmin()) load(); }, [limit, month]);

  async function openTrace(id) {
    if (!id) return;
    setErr(""); setTraceId(id);
    try { const r = await api(`/admin/audit/trace/${id}`, { admin: true }); setTrace(r.events || []); }
    catch (e) { setErr(String(e.message || e)); }
  }
  async function doVerify() {
    setErr(""); setVerify(null);
    try { setVerify(await api("/admin/audit/verify", { admin: true })); }
    catch (e) { setErr(String(e.message || e)); }
  }

  if (!canAdmin()) return <div className="card warn">You don’t have administrative access for this view.</div>;

  return (
    <div className="grid2">
      <div className="card">
        <h2>Audit ledger</h2>
        {err && <div className="error">{err}</div>}
        <div className="row" style={{ gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <label>Show
            <select value={limit} onChange={(e) => setLimit(Number(e.target.value))}>
              {[50, 100, 200].map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </label>
          <label>Month
            <input type="month" value={month} onChange={(e) => setMonth(e.target.value || currentMonthKey())} />
          </label>
          <button className="ghost" onClick={load}>Refresh</button>
          <button className="ghost" onClick={doVerify}>Verify chain</button>
          {scope && <small className="muted">scope: {scope}</small>}
        </div>
        {verify && (
          <div className={verify.ok ? "ok-msg" : "error"} style={{ marginTop: 8 }}>
            {verify.ok
              ? `Chain intact — verified ${verify.verified}/${verify.total} events${verify.truncated ? " (truncated)" : ""}`
              : `TAMPER DETECTED at sequence ${verify.failed_sequence_id}`}
          </div>
        )}
        <table>
          <thead><tr><th>#</th><th>Time</th><th>Tenant</th><th>Subject</th><th>Action</th><th>Resource</th><th>Decision</th><th></th></tr></thead>
          <tbody>
            {events.map((ev) => (
              <tr key={ev.sequence_id} className={ev.decision === "deny" ? "deny" : ""}>
                <td>{ev.sequence_id}</td>
                <td><small className="muted">{(ev.created_at || "").slice(0, 19).replace("T", " ")}</small></td>
                <td>{ev.tenant_id}</td><td><small>{ev.subject}</small></td>
                <td>{ev.action}</td><td><small>{ev.resource}</small></td>
                <td>{ev.decision}</td>
                <td><button className="ghost sm" onClick={() => openTrace(ev.trace_id)}>open</button></td>
              </tr>
            ))}
            {events.length === 0 && <tr><td colSpan="8" className="muted">No audit events.</td></tr>}
          </tbody>
        </table>
      </div>
      <div className="card">
        <h2>Trace {traceId && <small className="muted">{traceId.slice(0, 12)}…</small>}</h2>
        {!trace && <small className="muted">Open a trace to see its per-action policy decisions and hash links.</small>}
        {trace && (
          <table>
            <thead><tr><th>#</th><th>Action</th><th>Resource</th><th>Decision</th><th>Reason</th></tr></thead>
            <tbody>
              {trace.map((ev) => (
                <tr key={ev.sequence_id} className={ev.decision === "deny" ? "deny" : ""}>
                  <td>{ev.sequence_id}</td><td>{ev.action}</td><td><small>{ev.resource}</small></td>
                  <td>{ev.decision}</td><td><small className="muted">{ev.reason || ""}</small></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
