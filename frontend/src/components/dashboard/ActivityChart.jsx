import React from "react";
import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip, CartesianGrid } from "recharts";
import { chartTheme } from "../../theme/chartTheme.js";
import { useTheme } from "../../theme/useTheme.js";

export default function ActivityChart({ data }) {
  const { theme } = useTheme();
  const chart = chartTheme(theme);
  const series = (data || []).map((b) => ({
    h: b.hour ? new Date(b.hour).toLocaleTimeString([], { hour: "2-digit" }) : "",
    allow: b.allow, deny: b.deny,
  }));
  return (
    <div className="rounded-2xl border border-slate-700/60 bg-slate-800/70 p-5 col-span-2">
      <h3 className="text-sm font-semibold text-slate-200 mb-3">Activity (last 24h)</h3>
      <div className="h-56">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={series} margin={{ top: 10, right: 8, left: -10, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={chart.grid} />
            <XAxis dataKey="h" stroke={chart.axis} fontSize={11} />
            <YAxis stroke={chart.axis} fontSize={11} />
            <Tooltip contentStyle={chart.tooltip} />
            <Area type="monotone" dataKey="allow" stackId="1" stroke={chart.allow} fill={chart.allow} fillOpacity={0.25} />
            <Area type="monotone" dataKey="deny"  stackId="1" stroke={chart.deny} fill={chart.deny} fillOpacity={0.25} />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
