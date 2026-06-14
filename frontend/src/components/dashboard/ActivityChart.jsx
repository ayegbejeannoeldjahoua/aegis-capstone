import React from "react";
import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip, CartesianGrid } from "recharts";

export default function ActivityChart({ data }) {
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
            <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
            <XAxis dataKey="h" stroke="#64748b" fontSize={11} />
            <YAxis stroke="#64748b" fontSize={11} />
            <Tooltip contentStyle={{ background: "#1e293b", border: "1px solid #334155", borderRadius: 8 }} />
            <Area type="monotone" dataKey="allow" stackId="1" stroke="#10b981" fill="#10b981" fillOpacity={0.25} />
            <Area type="monotone" dataKey="deny"  stackId="1" stroke="#f43f5e" fill="#f43f5e" fillOpacity={0.25} />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
