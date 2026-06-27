import React from "react";

const COLOR_RING = {
  blue:    "bg-blue-500/15 text-blue-300",
  emerald: "bg-emerald-500/15 text-emerald-300",
  amber:   "bg-amber-500/15 text-amber-300",
  rose:    "bg-rose-500/15 text-rose-300",
  violet:  "bg-violet-500/15 text-violet-300",
  slate:   "bg-slate-500/15 text-slate-300",
};

function unpackMetric(value, unit, instrumented, note) {
  if (value && typeof value === "object" && Object.prototype.hasOwnProperty.call(value, "value")) {
    return {
      value: value.value,
      unit: unit ?? value.unit,
      instrumented: instrumented ?? value.instrumented,
      note: note ?? value.note,
    };
  }
  return { value, unit, instrumented, note };
}

function formatValue(value, unit, instrumented) {
  if (instrumented === false || value === null || value === undefined) return "No data";
  if (unit === "USD") return `$${Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 4 })}`;
  if (typeof value === "number") return Number(value).toLocaleString(undefined, { maximumFractionDigits: 1 });
  return value;
}

export default function MetricCard({ title, value, unit, icon: Icon, color = "blue", trendLabel, trend, instrumented, note }) {
  const metric = unpackMetric(value, unit, instrumented, note);
  const ring = COLOR_RING[color] || COLOR_RING.blue;
  const muted = metric.instrumented === false || metric.value === null || metric.value === undefined;
  const trendColor = trend === 1 ? "text-emerald-400" : trend === -1 ? "text-rose-400" : "text-slate-400";
  const display = formatValue(metric.value, metric.unit, metric.instrumented);
  return (
    <div className="rounded-2xl border border-slate-700/60 bg-slate-800/70 p-5">
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs uppercase tracking-wider text-slate-400 font-semibold">{title}</span>
        {Icon && <span className={`p-2 rounded-lg ${ring}`}><Icon className="h-4 w-4" /></span>}
      </div>
      <div className="flex items-baseline gap-1">
        <span className={`${muted ? "text-lg" : "text-3xl"} font-bold ${muted ? "text-slate-400" : "text-slate-100"}`}>{display}</span>
        {metric.unit && metric.unit !== "USD" && !muted && <span className="text-sm text-slate-400">{metric.unit}</span>}
      </div>
      {(trendLabel || metric.note) && <p className={`mt-2 text-xs ${metric.note ? "text-slate-500" : trendColor}`}>{metric.note || trendLabel}</p>}
    </div>
  );
}
