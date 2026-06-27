import React from "react";
import { CircleDollarSign, Flame, Gauge, Hash } from "lucide-react";
import MetricCard from "./MetricCard.jsx";

function List({ title, rows, labelKey, valueKey }) {
  return (
    <div>
      <h3 className="text-xs uppercase tracking-wider text-slate-400 font-semibold mb-2">{title}</h3>
      <ul className="space-y-2">
        {(rows || []).slice(0, 5).map((row) => (
          <li key={row[labelKey]} className="flex items-center justify-between text-sm">
            <span className="text-slate-300 truncate">{row[labelKey]}</span>
            <span className="text-slate-400">${Number(row[valueKey] || 0).toFixed(4)}</span>
          </li>
        ))}
        {(!rows || rows.length === 0) && <li className="text-sm text-slate-500">not instrumented</li>}
      </ul>
    </div>
  );
}

export default function FinOpsSummary({ finops }) {
  return (
    <section className="rounded-2xl border border-slate-700/60 bg-slate-800/70 p-5">
      <h2 className="text-sm font-semibold text-slate-200 mb-4">FinOps summary</h2>
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-5">
        <MetricCard title="Tokens today" value={finops?.tokens_today} icon={Hash} color="blue" />
        <MetricCard title="Estimated cost today" value={finops?.estimated_cost_today_usd} icon={CircleDollarSign} color="emerald" />
        <MetricCard title="Budget burn" value={finops?.budget_burn_pct} icon={Flame} color="amber" />
        <MetricCard title="Projected daily spend" value={finops?.projected_daily_spend_usd} icon={Gauge} color="violet" />
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <List title="Spend by tenant" rows={finops?.spend_by_tenant} labelKey="tenant_id" valueKey="cost_usd" />
        <List title="Spend by role" rows={finops?.spend_by_role} labelKey="role_id" valueKey="cost_usd" />
      </div>
      <div className="mt-4 grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm">
        <div className="rounded-xl bg-slate-900/40 border border-slate-700/50 px-3 py-2 text-slate-300">
          Top spending tenant: <span className="text-slate-100">{finops?.top_spending_tenant || "not instrumented"}</span>
        </div>
        <div className="rounded-xl bg-slate-900/40 border border-slate-700/50 px-3 py-2 text-slate-300">
          Top spending role: <span className="text-slate-100">{finops?.top_spending_role || "not instrumented"}</span>
        </div>
      </div>
    </section>
  );
}
