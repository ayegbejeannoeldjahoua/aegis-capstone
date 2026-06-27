import React from "react";
import { Wrench } from "lucide-react";

export default function InstrumentationGapsPanel({ gaps = [] }) {
  if (!gaps.length) return null;

  return (
    <section className="rounded-2xl border border-amber-500/25 bg-amber-500/10 p-4">
      <div className="flex items-center gap-2 mb-3">
        <span className="rounded-lg bg-amber-500/15 p-2 text-amber-300">
          <Wrench className="h-4 w-4" />
        </span>
        <h2 className="text-sm font-semibold text-amber-100">Instrumentation gaps</h2>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
        {gaps.map((gap) => (
          <div key={`${gap.metric}-${gap.reason}`} className="rounded-lg border border-amber-500/20 bg-slate-950/30 px-3 py-2">
            <div className="font-mono text-xs text-amber-200">{gap.metric}</div>
            <div className="mt-1 text-xs text-amber-100/75">{gap.reason}</div>
          </div>
        ))}
      </div>
    </section>
  );
}
