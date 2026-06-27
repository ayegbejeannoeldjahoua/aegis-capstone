import React from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

const LATENCY_KEYS = [
  ["p95_pdp_latency_ms", "PDP"],
  ["p95_retrieval_latency_ms", "Retrieval"],
  ["p95_model_latency_ms", "Model"],
  ["p95_pii_inspection_latency_ms", "PII"],
  ["p95_audit_write_latency_ms", "Audit"],
  ["p95_isa_verification_latency_ms", "ISA"],
  ["p95_finops_write_latency_ms", "FinOps"],
];

function metricValue(metric) {
  return metric?.instrumented === false || metric?.value == null ? null : Number(metric.value);
}

export default function LatencyBreakdownChart({ latency }) {
  const bars = LATENCY_KEYS.map(([key, label]) => ({
    stage: label,
    ms: metricValue(latency?.[key]) ?? 0,
    instrumented: latency?.[key]?.instrumented !== false && latency?.[key]?.value != null,
  }));
  const e2e = latency?.e2e_latency_ms || {};
  const hasBars = bars.some((b) => b.instrumented);
  return (
    <section className="rounded-2xl border border-slate-700/60 bg-slate-800/70 p-5">
      <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between mb-4">
        <h2 className="text-sm font-semibold text-slate-200">Latency breakdown</h2>
        <div className="flex gap-3 text-xs text-slate-400">
          <span>p50 e2e: {metricValue(e2e.p50) ?? "not instrumented"} ms</span>
          <span>p95 e2e: {metricValue(e2e.p95) ?? "not instrumented"} ms</span>
          <span>p99 e2e: {metricValue(e2e.p99) ?? "not instrumented"} ms</span>
        </div>
      </div>
      <div className="h-64">
        {hasBars ? (
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={bars} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
              <XAxis dataKey="stage" stroke="#64748b" fontSize={11} />
              <YAxis stroke="#64748b" fontSize={11} />
              <Tooltip contentStyle={{ background: "#1e293b", border: "1px solid #334155", borderRadius: 8 }} />
              <Bar dataKey="ms" fill="#38bdf8" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <div className="flex h-full items-center justify-center text-sm text-slate-500">not instrumented</div>
        )}
      </div>
    </section>
  );
}
