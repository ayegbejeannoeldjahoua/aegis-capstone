import React from "react";
import { GitBranch, Rows3, ShieldCheck } from "lucide-react";
import MetricCard from "./MetricCard.jsx";

export default function AuditTraceSummary({ audit }) {
  const chain = audit?.audit_chain_verification || {};
  return (
    <section className="rounded-2xl border border-slate-700/60 bg-slate-800/70 p-5">
      <h2 className="text-sm font-semibold text-slate-200 mb-4">Audit and trace summary</h2>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-5">
        <MetricCard title="Audit events today" value={audit?.audit_events_today} icon={Rows3} color="blue" />
        <MetricCard title="Avg audit rows / turn" value={audit?.average_audit_rows_per_chat_turn} icon={GitBranch} color="violet" />
        <MetricCard title="Trace coverage" value={audit?.trace_coverage_pct} icon={ShieldCheck} color="emerald" />
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div>
          <h3 className="text-xs uppercase tracking-wider text-slate-400 font-semibold mb-2">Audit chain</h3>
          <div className={`rounded-xl border px-3 py-2 text-sm ${chain.ok ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300" : "border-rose-500/40 bg-rose-500/10 text-rose-300"}`}>
            {chain.ok ? `verified ${chain.verified || 0} / ${chain.total || 0}` : chain.error || "verification failed"}
          </div>
        </div>
        <div>
          <h3 className="text-xs uppercase tracking-wider text-slate-400 font-semibold mb-2">Top deny reasons</h3>
          <ul className="space-y-2">
            {(audit?.top_deny_reasons || []).slice(0, 5).map((r) => (
              <li key={r.reason} className="flex justify-between gap-3 text-sm">
                <span className="text-slate-300 truncate">{r.reason}</span>
                <span className="text-slate-400">{r.count}</span>
              </li>
            ))}
            {(!audit?.top_deny_reasons || audit.top_deny_reasons.length === 0) && <li className="text-sm text-slate-500">no denies today</li>}
          </ul>
        </div>
      </div>
      <div className="mt-5">
        <h3 className="text-xs uppercase tracking-wider text-slate-400 font-semibold mb-2">Recent trace IDs</h3>
        <div className="flex flex-wrap gap-2">
          {(audit?.recent_trace_ids || []).slice(0, 10).map((id) => (
            <span key={id} className="rounded-lg bg-slate-900/60 border border-slate-700/50 px-2 py-1 font-mono text-xs text-slate-300">{id}</span>
          ))}
          {(!audit?.recent_trace_ids || audit.recent_trace_ids.length === 0) && <span className="text-sm text-slate-500">no traces today</span>}
        </div>
      </div>
    </section>
  );
}
