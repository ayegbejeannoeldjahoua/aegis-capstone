import React from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

const LATENCY_KEYS = [
  ["pdp", "PDP"],
  ["retrieval", "Retrieval"],
  ["model", "Model"],
  ["audit_write", "Audit"],
  ["isa", "ISA"],
];

function latencyValue(stage) {
  const value = stage?.p95_ms;
  return value === null || value === undefined ? null : Number(value);
}

function formatMs(value) {
  return value === null || value === undefined ? "No data" : `${Number(value).toLocaleString(undefined, { maximumFractionDigits: 1 })} ms`;
}

export default function LatencyBreakdownChart({ latency }) {
  const bars = LATENCY_KEYS.map(([key, label]) => ({
    stage: label,
    ms: latencyValue(latency?.[key]) ?? 0,
    available: latencyValue(latency?.[key]) !== null,
  }));
  const e2e = latency?.end_to_end || {};
  const hasBars = bars.some((b) => b.available);
  return (
    <section className="rounded-2xl border border-slate-700/60 bg-slate-800/70 p-5">
      <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between mb-4">
        <h2 className="text-sm font-semibold text-slate-200">Latency breakdown</h2>
        <div className="flex gap-3 text-xs text-slate-400">
          <span>p50 e2e: {formatMs(e2e.p50_ms)}</span>
          <span>p95 e2e: {formatMs(e2e.p95_ms)}</span>
          <span>p99 e2e: {formatMs(e2e.p99_ms)}</span>
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
          <div className="flex h-full items-center justify-center text-sm text-slate-500">No stage timings recorded today</div>
        )}
      </div>
    </section>
  );
}
