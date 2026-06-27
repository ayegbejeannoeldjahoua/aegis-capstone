import React from "react";
import Badge from "../common/Badge.jsx";

export default function RecentDecisionsTable({ decisions }) {
  return (
    <section className="rounded-2xl border border-slate-700/60 bg-slate-800/70 p-5">
      <h2 className="text-sm font-semibold text-slate-200 mb-4">Recent decisions</h2>
      <div className="overflow-auto">
        <table className="min-w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wider text-slate-500">
              <th className="py-2 pr-4">Decision</th>
              <th className="py-2 pr-4">Action</th>
              <th className="py-2 pr-4">Tenant</th>
              <th className="py-2 pr-4">Subject</th>
              <th className="py-2 pr-4">Trace</th>
              <th className="py-2">Reason</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-700/50">
            {(decisions || []).slice(0, 20).map((row, i) => (
              <tr key={`${row.trace_id}-${row.action}-${i}`} className="text-slate-300">
                <td className="py-2 pr-4"><Badge variant={row.decision === "allow" ? "allow" : "deny"}>{row.decision}</Badge></td>
                <td className="py-2 pr-4 font-mono text-xs text-slate-400">{row.action}</td>
                <td className="py-2 pr-4">{row.tenant_id}</td>
                <td className="py-2 pr-4 truncate max-w-[180px]">{row.subject}</td>
                <td className="py-2 pr-4 font-mono text-xs text-slate-400 truncate max-w-[180px]">{row.trace_id}</td>
                <td className="py-2 text-slate-400 truncate max-w-[260px]">{row.reason || "—"}</td>
              </tr>
            ))}
            {(!decisions || decisions.length === 0) && (
              <tr><td colSpan={6} className="py-4 text-slate-500">no decisions today</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
