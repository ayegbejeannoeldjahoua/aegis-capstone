import React, { useEffect, useState } from "react";
import { DollarSign, TrendingUp, ShieldX } from "lucide-react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, PieChart, Pie, Cell, Legend } from "recharts";
import { api } from "../api/client.js";
import MetricCard from "../components/dashboard/MetricCard.jsx";

const PIE_COLORS = { "model.call": "#3b82f6", "tool.call": "#10b981", "memory.read": "#f59e0b", "memory.write": "#8b5cf6" };

function BudgetRow({ team, budget_usd, spent_usd }) {
  const pct = budget_usd > 0 ? Math.min((spent_usd / budget_usd) * 100, 100) : 0;
  const color = pct < 60 ? "bg-emerald-500" : pct < 85 ? "bg-amber-500" : "bg-rose-500";
  return (
    <div className="px-4 py-3 hover:bg-slate-700/20 transition-colors">
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-sm text-slate-300 font-medium">{team}</span>
        <span className="text-xs text-slate-500 font-mono">${spent_usd.toFixed(4)} / ${budget_usd.toFixed(2)}</span>
      </div>
      <div className="h-1.5 rounded-full bg-slate-700">
        <div className={`h-1.5 rounded-full ${color} transition-all`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

export default function FinOps() {
  const [summary, setSummary] = useState(null);
  const [budget, setBudget] = useState([]);
  const [err, setErr] = useState("");

  useEffect(() => {
    api("/admin/finops/summary").then(setSummary).catch(e => setErr(String(e.message || e)));
    api("/admin/finops/budget").then(d => setBudget(d.teams || [])).catch(() => {});
  }, []);

  const tenantData = Object.entries(summary?.by_tenant || {}).map(([name, count]) => ({ name, count }));
  const actionData = Object.entries(summary?.by_action || {}).map(([name, d]) => ({ name, value: d.count }));

  return (
    <div className="space-y-5">
      {err && <div className="error">{err}</div>}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <MetricCard title="Spend (24h)" value={`$${(summary?.total_cost_usd ?? 0).toFixed(4)}`}
                    icon={DollarSign} color="blue" trendLabel="estimated" />
        <MetricCard title="Model calls" value={summary?.by_action?.["model.call"]?.count ?? 0}
                    icon={TrendingUp} color="emerald" trendLabel="last 24h" />
        <MetricCard title="Denied on budget" value={summary?.denied_on_budget ?? 0}
                    icon={ShieldX} color="amber" trendLabel="model.call denies" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="rounded-2xl border border-slate-700/60 bg-slate-800/70 p-5">
          <h3 className="text-sm font-semibold text-slate-200 mb-3">Activity by tenant</h3>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={tenantData}>
                <XAxis dataKey="name" stroke="#64748b" fontSize={11} />
                <YAxis stroke="#64748b" fontSize={11} />
                <Tooltip contentStyle={{ background: "#1e293b", border: "1px solid #334155", borderRadius: 8 }} />
                <Bar dataKey="count" fill="#3b82f6" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="rounded-2xl border border-slate-700/60 bg-slate-800/70 p-5">
          <h3 className="text-sm font-semibold text-slate-200 mb-3">Mix by action</h3>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={actionData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={80}>
                  {actionData.map((d, i) => (
                    <Cell key={i} fill={PIE_COLORS[d.name] || "#64748b"} />
                  ))}
                </Pie>
                <Legend />
                <Tooltip contentStyle={{ background: "#1e293b", border: "1px solid #334155", borderRadius: 8 }} />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      <div className="rounded-2xl border border-slate-700/60 bg-slate-800/70 overflow-hidden">
        <h3 className="text-sm font-semibold text-slate-200 px-4 pt-4">Team budgets</h3>
        <div className="divide-y divide-slate-700/60 mt-3">
          {budget.length === 0 && <div className="px-4 py-6 text-xs text-slate-500">no budgets yet</div>}
          {budget.map((b, i) => <BudgetRow key={i} {...b} />)}
        </div>
      </div>
    </div>
  );
}
