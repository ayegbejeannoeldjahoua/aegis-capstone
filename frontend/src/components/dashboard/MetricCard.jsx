import React from "react";

const COLOR_RING = {
  blue:    "bg-blue-500/15 text-blue-300",
  emerald: "bg-emerald-500/15 text-emerald-300",
  amber:   "bg-amber-500/15 text-amber-300",
  rose:    "bg-rose-500/15 text-rose-300",
  violet:  "bg-violet-500/15 text-violet-300",
};

export default function MetricCard({ title, value, unit, icon: Icon, color = "blue", trendLabel, trend }) {
  const ring = COLOR_RING[color] || COLOR_RING.blue;
  const trendColor = trend === 1 ? "text-emerald-400" : trend === -1 ? "text-rose-400" : "text-slate-400";
  return (
    <div className="rounded-2xl border border-slate-700/60 bg-slate-800/70 p-5">
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs uppercase tracking-wider text-slate-400 font-semibold">{title}</span>
        {Icon && <span className={`p-2 rounded-lg ${ring}`}><Icon className="h-4 w-4" /></span>}
      </div>
      <div className="flex items-baseline gap-1">
        <span className="text-3xl font-bold text-slate-100">{value}</span>
        {unit && <span className="text-sm text-slate-400">{unit}</span>}
      </div>
      {trendLabel && <p className={`mt-2 text-xs ${trendColor}`}>{trendLabel}</p>}
    </div>
  );
}
