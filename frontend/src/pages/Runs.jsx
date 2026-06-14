import React, { Fragment, useEffect, useState } from "react";
import { Activity, ChevronDown, ChevronRight, FileCheck2, RefreshCw, X } from "lucide-react";
import { api } from "../api/client.js";
import Badge from "../components/common/Badge.jsx";
import EmptyState from "../components/common/EmptyState.jsx";

const STATE_VARIANT = { completed: "allow", blocked: "deny" };

function EvidencePanel({ pkg, onClose }) {
  return (
    <div className="rounded-xl border border-blue-500/30 bg-slate-900 p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="flex items-center gap-2 text-sm font-semibold text-blue-300">
          <FileCheck2 className="h-4 w-4" /> Evidence package
          <span className="font-mono text-xs text-slate-500">{pkg.evidence_id}</span>
        </h3>
        <button onClick={onClose} className="ghost p-1"><X className="h-4 w-4" /></button>
      </div>
      <div className="grid grid-cols-4 gap-3 text-xs">
        <div><span className="text-slate-500">events</span>
          <div className="text-lg font-bold text-slate-200">{pkg.event_count}</div></div>
        <div><span className="text-slate-500">denials</span>
          <div className={`text-lg font-bold ${pkg.deny_count ? "text-rose-400" : "text-emerald-400"}`}>{pkg.deny_count}</div></div>
        <div><span className="text-slate-500">cost</span>
          <div className="text-lg font-bold text-slate-200">${pkg.total_cost_usd}</div></div>
        <div><span className="text-slate-500">policy</span>
          <div className="font-mono text-xs text-slate-300 pt-2">{pkg.policy_version}</div></div>
      </div>
      <details className="text-xs">
        <summary className="cursor-pointer text-slate-400">events ({pkg.event_count})</summary>
        <ul className="mt-2 space-y-1 max-h-72 overflow-auto">
          {pkg.events.map((e) => (
            <li key={e.sequence_id} className="font-mono text-slate-300">
              <Badge variant={e.decision === "allow" ? "allow" : "deny"}>{e.decision}</Badge>
              <span className="ml-2">{e.action}</span>
              <span className="ml-2 text-slate-500">{e.subject}</span>
              {e.reason && <span className="ml-2 text-rose-300">{e.reason}</span>}
            </li>
          ))}
        </ul>
      </details>
    </div>
  );
}

export default function Runs() {
  const [runs, setRuns] = useState([]);
  const [expanded, setExpanded] = useState(null);
  const [pkg, setPkg] = useState(null);
  const [err, setErr] = useState("");

  async function load() {
    setErr("");
    try { const r = await api("/admin/runs"); setRuns(r.runs || []); }
    catch (e) { setErr(String(e.message || e)); }
  }
  useEffect(() => { load(); }, []);

  async function openEvidence(trace_id) {
    setExpanded(trace_id);
    try { const p = await api(`/admin/evidence/${trace_id}`); setPkg(p); }
    catch (e) { setErr(String(e.message || e)); }
  }

  return (
    <div className="space-y-5">
      {err && <div className="error">{err}</div>}
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-200">Recent runs</h3>
        <button className="ghost" onClick={load}><RefreshCw className="h-3 w-3 inline mr-1" /> refresh</button>
      </div>
      <div className="rounded-2xl border border-slate-700/60 bg-slate-800/70 overflow-hidden">
        {runs.length === 0 && <EmptyState title="No runs yet" hint="Send a chat to generate audit events." icon={Activity} />}
        <table className="w-full text-sm">
          <thead><tr>
            <th className="text-left text-xs text-slate-400 py-2 px-4">trace</th>
            <th className="text-left text-xs text-slate-400 py-2 px-4">tenant</th>
            <th className="text-left text-xs text-slate-400 py-2 px-4">events</th>
            <th className="text-left text-xs text-slate-400 py-2 px-4">deny</th>
            <th className="text-left text-xs text-slate-400 py-2 px-4">state</th>
            <th className="text-left text-xs text-slate-400 py-2 px-4">policy</th>
            <th className="text-left text-xs text-slate-400 py-2 px-4">started</th>
          </tr></thead>
          <tbody>
            {runs.map((r) => (
              <Fragment key={r.trace_id}>
                <tr className="border-t border-slate-700/40 hover:bg-slate-700/20 cursor-pointer"
                    onClick={() => openEvidence(r.trace_id)}>
                  <td className="py-2 px-4 font-mono text-xs text-slate-300">
                    {expanded === r.trace_id ? <ChevronDown className="inline h-3 w-3 mr-1" /> : <ChevronRight className="inline h-3 w-3 mr-1" />}
                    {(r.trace_id || "").slice(0, 12)}…
                  </td>
                  <td className="py-2 px-4 text-slate-300">{r.tenant_id}</td>
                  <td className="py-2 px-4">{r.event_count}</td>
                  <td className="py-2 px-4 text-rose-300">{r.deny_count}</td>
                  <td className="py-2 px-4"><Badge variant={STATE_VARIANT[r.state] || "neutral"}>{r.state}</Badge></td>
                  <td className="py-2 px-4 font-mono text-xs text-slate-400">{r.policy_version}</td>
                  <td className="py-2 px-4 text-xs text-slate-400">{(r.started_at || "").slice(0, 19)}</td>
                </tr>
                {expanded === r.trace_id && pkg && pkg.trace_id === r.trace_id && (
                  <tr><td colSpan="7" className="px-4 pb-4"><EvidencePanel pkg={pkg} onClose={() => { setExpanded(null); setPkg(null); }} /></td></tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
