import React from "react";
import { Database, FileSearch, Layers, SearchX } from "lucide-react";
import MetricCard from "./MetricCard.jsx";

function available(value) {
  return value !== null && value !== undefined;
}

function Bars({ rows, labelKey }) {
  const max = Math.max(1, ...(rows || []).map((r) => Number(r.count || 0)));
  return (
    <ul className="space-y-2">
      {(rows || []).slice(0, 6).map((row) => (
        <li key={row[labelKey]} className="text-sm">
          <div className="flex justify-between gap-3 mb-1">
            <span className="text-slate-300 truncate">{row[labelKey]}</span>
            <span className="text-slate-400">{row.count}</span>
          </div>
          <div className="h-1.5 rounded-full bg-slate-900/80">
            <div className="h-1.5 rounded-full bg-sky-400" style={{ width: `${Math.max(6, (Number(row.count || 0) / max) * 100)}%` }} />
          </div>
        </li>
      ))}
      {(!rows || rows.length === 0) && <li className="text-sm text-slate-500">No retrieval activity today</li>}
    </ul>
  );
}

export default function RetrievalSummary({ retrieval }) {
  return (
    <section className="rounded-2xl border border-slate-700/60 bg-slate-800/70 p-5">
      <h2 className="text-sm font-semibold text-slate-200 mb-4">Retrieval summary</h2>
      <div className="grid grid-cols-1 md:grid-cols-5 gap-4 mb-5">
        <MetricCard title="Retrieval calls" value={retrieval?.calls_today ?? 0} icon={FileSearch} color="blue" />
        <MetricCard title="Retrieved docs" value={retrieval?.documents_returned_today ?? 0} icon={Database} color="blue" />
        {available(retrieval?.avg_docs_per_turn) && (
          <MetricCard title="Avg docs / turn" value={retrieval.avg_docs_per_turn} icon={Database} color="violet" />
        )}
        <MetricCard title="Zero-result retrievals" value={retrieval?.zero_result_count ?? 0} icon={SearchX} color="amber" />
        {available(retrieval?.cross_tenant_leakage_alerts) && (
          <MetricCard title="Leakage alerts" value={retrieval.cross_tenant_leakage_alerts} icon={Layers} color={(retrieval.cross_tenant_leakage_alerts || 0) === 0 ? "emerald" : "rose"} />
        )}
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div>
          <h3 className="text-xs uppercase tracking-wider text-slate-400 font-semibold mb-2">By namespace</h3>
          <Bars rows={retrieval?.by_namespace} labelKey="namespace" />
        </div>
        <div>
          <h3 className="text-xs uppercase tracking-wider text-slate-400 font-semibold mb-2">By classification</h3>
          <Bars rows={retrieval?.by_classification} labelKey="classification" />
        </div>
      </div>
    </section>
  );
}
