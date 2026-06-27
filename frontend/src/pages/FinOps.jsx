import React, { useEffect, useState } from "react";
import { DollarSign, Gauge, Hash, RefreshCw, ShieldX, TrendingUp } from "lucide-react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api/client.js";
import MetricCard from "../components/dashboard/MetricCard.jsx";
import InstrumentationGapsPanel from "../components/dashboard/InstrumentationGapsPanel.jsx";

function available(value) {
  return value !== null && value !== undefined;
}

function compact(value) {
  if (!available(value)) return "No data";
  return Number(value).toLocaleString(undefined, { notation: "compact", maximumFractionDigits: 1 });
}

function money(value) {
  if (!available(value)) return "No data";
  return `$${Number(value).toLocaleString(undefined, { maximumFractionDigits: 4 })}`;
}

function pct(value) {
  if (!available(value)) return "No data";
  return `${Number(value).toLocaleString(undefined, { maximumFractionDigits: 1 })}%`;
}

function Panel({ title, children }) {
  return (
    <section className="rounded-2xl border border-slate-700/60 bg-slate-800/70 p-5">
      <h2 className="text-sm font-semibold text-slate-200 mb-4">{title}</h2>
      {children}
    </section>
  );
}

function BreakdownList({ title, rows, labelKey, valueKey, formatter, empty = "No records in this window" }) {
  const max = Math.max(1, ...(rows || []).map((row) => Number(row[valueKey] || 0)));
  return (
    <div>
      <h3 className="text-xs uppercase tracking-wider text-slate-400 font-semibold mb-2">{title}</h3>
      <ul className="space-y-2">
        {(rows || []).slice(0, 6).map((row) => (
          <li key={row[labelKey]} className="text-sm">
            <div className="flex justify-between gap-3 mb-1">
              <span className="text-slate-300 truncate">{row[labelKey] || "unknown"}</span>
              <span className="text-slate-400">{formatter(row[valueKey])}</span>
            </div>
            <div className="h-1.5 rounded-full bg-slate-900/80">
              <div className="h-1.5 rounded-full bg-sky-400" style={{ width: `${Math.max(6, (Number(row[valueKey] || 0) / max) * 100)}%` }} />
            </div>
          </li>
        ))}
        {(!rows || rows.length === 0) && <li className="text-sm text-slate-500">{empty}</li>}
      </ul>
    </div>
  );
}

function BudgetRow({ tenant_id, role_id, token_budget_per_day, budget_tokens, tokens_used, spent_tokens, remaining_tokens, utilization_pct }) {
  const used = Number(tokens_used ?? spent_tokens ?? 0);
  const budget = Number(token_budget_per_day ?? budget_tokens ?? 0);
  const pctValue = available(utilization_pct) ? Number(utilization_pct) : (budget > 0 ? Math.min((used / budget) * 100, 100) : 0);
  const color = pctValue < 60 ? "bg-emerald-500" : pctValue < 85 ? "bg-amber-500" : "bg-rose-500";
  return (
    <div className="py-3">
      <div className="flex items-center justify-between gap-3 mb-1.5">
        <span className="text-sm text-slate-300 font-medium">{tenant_id}/{role_id}</span>
        <span className="text-xs text-slate-500 font-mono">{compact(used)} / {compact(budget)} tokens</span>
      </div>
      <div className="h-1.5 rounded-full bg-slate-900/80">
        <div className={`h-1.5 rounded-full ${color} transition-all`} style={{ width: `${Math.min(pctValue, 100)}%` }} />
      </div>
      <div className="mt-1 text-xs text-slate-500">{pct(pctValue)} used · {compact(remaining_tokens ?? 0)} remaining</div>
    </div>
  );
}

function RecentFinOpsEvents({ events }) {
  return (
    <Panel title="Recent FinOps events">
      <div className="overflow-auto">
        <table className="min-w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wider text-slate-500">
              <th className="py-2 pr-4">Time</th>
              <th className="py-2 pr-4">Trace</th>
              <th className="py-2 pr-4">Tenant</th>
              <th className="py-2 pr-4">Role</th>
              <th className="py-2 pr-4">Model</th>
              <th className="py-2 pr-4">Input</th>
              <th className="py-2 pr-4">Output</th>
              <th className="py-2 pr-4">Cost</th>
              <th className="py-2">Budget</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-700/50">
            {(events || []).slice(0, 25).map((row, index) => (
              <tr key={`${row.trace_id}-${index}`} className="text-slate-300">
                <td className="py-2 pr-4 text-xs text-slate-500">{row.timestamp ? new Date(row.timestamp).toLocaleTimeString() : "No data"}</td>
                <td className="py-2 pr-4 font-mono text-xs text-slate-400 truncate max-w-[180px]">{row.trace_id}</td>
                <td className="py-2 pr-4">{row.tenant_id}</td>
                <td className="py-2 pr-4">{row.role}</td>
                <td className="py-2 pr-4">{row.model || row.provider || "No data"}</td>
                <td className="py-2 pr-4 text-slate-400">{compact(row.input_tokens)}</td>
                <td className="py-2 pr-4 text-slate-400">{compact(row.output_tokens)}</td>
                <td className="py-2 pr-4 text-slate-400">{money(row.estimated_cost)}</td>
                <td className="py-2 text-slate-400">{row.budget_status || "No data"}</td>
              </tr>
            ))}
            {(!events || events.length === 0) && (
              <tr><td colSpan={9} className="py-4 text-slate-500">No FinOps events in this window</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

export default function FinOps() {
  const [summary, setSummary] = useState(null);
  const [budget, setBudget] = useState([]);
  const [err, setErr] = useState("");

  async function load() {
    setErr("");
    try {
      const s = await api("/admin/finops/summary");
      setSummary(s);
      const b = await api("/admin/finops/budget").catch(() => ({ teams: [] }));
      setBudget(b.teams || []);
    } catch (e) {
      setErr(String(e.message || e));
    }
  }

  useEffect(() => { load(); }, []);

  const fin = summary?.summary || {};
  const breakdowns = summary?.breakdowns || {};
  const tokens = summary?.token_breakdown || {};
  const budgets = summary?.budget_governance || {};
  const budgetRows = (budgets.daily_budgets || []).length ? budgets.daily_budgets : budget;
  const costByHour = (breakdowns.by_hour || []).map((row) => ({
    hour: row.hour ? new Date(row.hour).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "unknown",
    cost: Number(row.cost_usd || 0),
  }));
  const tokenByHour = (tokens.by_hour || []).map((row) => ({
    hour: row.hour ? new Date(row.hour).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "unknown",
    tokens: Number(row.tokens || 0),
  }));

  return (
    <div className="space-y-5">
      {err && <div className="error">{err}</div>}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-lg font-semibold text-slate-100">FinOps</h1>
          <div className="text-xs text-slate-500">
            {summary?.scope?.admin_scope === "tenant" ? `Tenant scope: ${summary.scope.tenant_id}` : "Platform scope"}
            {summary?.hours ? ` · last ${summary.hours}h` : ""}
          </div>
        </div>
        <button type="button" onClick={load} className="inline-flex items-center gap-2 rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200 hover:bg-slate-700">
          <RefreshCw className="h-4 w-4" /> Refresh
        </button>
      </div>

      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-slate-200">Executive FinOps</h2>
        <div className="grid grid-cols-1 md:grid-cols-3 xl:grid-cols-6 gap-4">
          {available(fin.tokens_today) && <MetricCard title="Tokens today" value={fin.tokens_today} icon={Hash} color="blue" />}
          {available(fin.estimated_cost_today) && <MetricCard title="Estimated cost today" value={fin.estimated_cost_today} unit="USD" icon={DollarSign} color="emerald" />}
          {available(fin.avg_cost_per_turn) && <MetricCard title="Avg cost / chat turn" value={fin.avg_cost_per_turn} unit="USD" icon={TrendingUp} color="blue" />}
          {available(fin.budget_utilization_pct) && <MetricCard title="Budget utilization" value={fin.budget_utilization_pct} unit="%" icon={Gauge} color={fin.budget_utilization_pct > 85 ? "rose" : fin.budget_utilization_pct > 60 ? "amber" : "emerald"} />}
          {available(fin.budget_refusals) && <MetricCard title="Budget refusals" value={fin.budget_refusals} icon={ShieldX} color="amber" />}
          {available(fin.projected_daily_spend) && <MetricCard title="Projected daily spend" value={fin.projected_daily_spend} unit="USD" icon={TrendingUp} color="violet" />}
        </div>
      </section>

      <InstrumentationGapsPanel gaps={summary?.instrumentation_gaps || []} />

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <Panel title="Cost breakdown">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <BreakdownList title="Spend by tenant" rows={breakdowns.by_tenant} labelKey="tenant_id" valueKey="cost_usd" formatter={money} empty="No cost records yet" />
            <BreakdownList title="Spend by role" rows={breakdowns.by_role} labelKey="role_id" valueKey="cost_usd" formatter={money} empty="No cost records yet" />
            <BreakdownList title="Spend by model" rows={breakdowns.by_model} labelKey="model" valueKey="cost_usd" formatter={money} empty="No model cost attribution yet" />
            <BreakdownList title="Spend by provider" rows={breakdowns.by_provider} labelKey="provider" valueKey="cost_usd" formatter={money} empty="No provider cost attribution yet" />
          </div>
          <div className="mt-5 h-52">
            {costByHour.length ? (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={costByHour} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                  <XAxis dataKey="hour" stroke="#64748b" fontSize={11} />
                  <YAxis stroke="#64748b" fontSize={11} />
                  <Tooltip contentStyle={{ background: "#1e293b", border: "1px solid #334155", borderRadius: 8 }} formatter={(value) => money(value)} />
                  <Bar dataKey="cost" fill="#10b981" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="flex h-full items-center justify-center text-sm text-slate-500">No hourly cost records yet</div>
            )}
          </div>
        </Panel>

        <Panel title="Token breakdown">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-5 text-sm">
            <div className="rounded-xl bg-slate-900/40 border border-slate-700/50 px-3 py-2 text-slate-300">Input: <span className="text-slate-100">{compact(tokens.input_tokens)}</span></div>
            <div className="rounded-xl bg-slate-900/40 border border-slate-700/50 px-3 py-2 text-slate-300">Output: <span className="text-slate-100">{compact(tokens.output_tokens)}</span></div>
            <div className="rounded-xl bg-slate-900/40 border border-slate-700/50 px-3 py-2 text-slate-300">Total: <span className="text-slate-100">{compact(tokens.total_tokens)}</span></div>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <BreakdownList title="Tokens by tenant" rows={tokens.by_tenant} labelKey="tenant_id" valueKey="tokens" formatter={compact} />
            <BreakdownList title="Tokens by role" rows={tokens.by_role} labelKey="role_id" valueKey="tokens" formatter={compact} />
            <BreakdownList title="Tokens by model" rows={tokens.by_model} labelKey="model" valueKey="tokens" formatter={compact} empty="No model token attribution yet" />
            <BreakdownList title="Tokens by provider" rows={tokens.by_provider} labelKey="provider" valueKey="tokens" formatter={compact} empty="No provider token attribution yet" />
          </div>
          <div className="mt-5 h-52">
            {tokenByHour.length ? (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={tokenByHour} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                  <XAxis dataKey="hour" stroke="#64748b" fontSize={11} />
                  <YAxis stroke="#64748b" fontSize={11} />
                  <Tooltip contentStyle={{ background: "#1e293b", border: "1px solid #334155", borderRadius: 8 }} formatter={(value) => compact(value)} />
                  <Bar dataKey="tokens" fill="#38bdf8" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="flex h-full items-center justify-center text-sm text-slate-500">No hourly token records yet</div>
            )}
          </div>
        </Panel>
      </div>

      <Panel title="Budget governance">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-4 text-sm">
          <div className="rounded-xl bg-slate-900/40 border border-slate-700/50 px-3 py-2 text-slate-300">Current burn: <span className="text-slate-100">{compact(budgets.current_burn_tokens)}</span></div>
          <div className="rounded-xl bg-slate-900/40 border border-slate-700/50 px-3 py-2 text-slate-300">Remaining: <span className="text-slate-100">{compact(budgets.remaining_budget_tokens)}</span></div>
          <div className="rounded-xl bg-slate-900/40 border border-slate-700/50 px-3 py-2 text-slate-300">Refusals: <span className="text-slate-100">{compact(budgets.budget_refusal_count ?? fin.budget_refusals)}</span></div>
        </div>
        <div className="divide-y divide-slate-700/60">
          {(budgetRows || []).slice(0, 12).map((row) => <BudgetRow key={`${row.tenant_id}-${row.role_id}`} {...row} />)}
          {(!budgetRows || budgetRows.length === 0) && <div className="py-4 text-sm text-slate-500">No role budgets configured</div>}
        </div>
      </Panel>

      <RecentFinOpsEvents events={summary?.recent_events || []} />
    </div>
  );
}
