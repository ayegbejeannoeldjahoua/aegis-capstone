import React, { useEffect, useState } from "react";
import { Activity, Gauge, Hash, RefreshCw, ShieldX } from "lucide-react";
import { Bar, BarChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api/client.js";
import MetricCard from "../components/dashboard/MetricCard.jsx";
import { chartTheme } from "../theme/chartTheme.js";
import { useTheme } from "../theme/useTheme.js";

const PIE_COLORS = [
  "var(--chart-bar)",
  "var(--chart-allow)",
  "var(--chart-cost)",
  "var(--chart-deny)",
  "var(--blue)",
  "var(--emerald)",
  "var(--amber)",
  "var(--violet)",
];

function currentMonthKey() {
  return new Date().toISOString().slice(0, 7);
}

function available(value) {
  return value !== null && value !== undefined;
}

function compact(value) {
  if (!available(value)) return "No data";
  return Number(value).toLocaleString(undefined, { notation: "compact", maximumFractionDigits: 1 });
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

function BudgetRow({ tenant_id, role_id, monthly_token_budget, token_budget_per_day, tokens_used, spent_tokens, remaining_tokens, utilization_pct }) {
  const used = Number(tokens_used ?? spent_tokens ?? 0);
  const budget = Number(monthly_token_budget ?? token_budget_per_day ?? 0);
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

function BudgetGovernance({ budgets, fin, budgetRows, budgetEmpty }) {
  const eventCount = Number(budgets.event_count || 0);
  const refusals = Number(budgets.budget_refusal_count ?? fin.budget_refusals ?? 0);
  const routed = Number(budgets.model_routed_count || 0);
  const unmetered = Number(budgets.unmetered_count || 0);
  return (
    <details className="rounded-2xl border border-slate-700/60 bg-slate-800/70">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-4 px-5 py-4">
        <div>
          <h2 className="text-sm font-semibold text-slate-200">Budget Governance</h2>
          <p className="mt-1 text-xs text-slate-500">
            {compact(eventCount)} checks · {compact(routed)} routed · {compact(refusals)} refusals
            {unmetered ? ` · ${compact(unmetered)} unmetered` : ""}
          </p>
        </div>
        <span className="rounded-lg border border-slate-700 px-2.5 py-1 text-xs text-slate-300">Expand</span>
      </summary>
      <div className="border-t border-slate-700/60 px-5 pb-5 pt-4">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-4 text-sm">
          <div className="rounded-xl bg-slate-900/40 border border-slate-700/50 px-3 py-2 text-slate-300">Month burn: <span className="text-slate-100">{compact(budgets.current_burn_tokens)}</span></div>
          <div className="rounded-xl bg-slate-900/40 border border-slate-700/50 px-3 py-2 text-slate-300">Remaining: <span className="text-slate-100">{compact(budgets.remaining_budget_tokens)}</span></div>
          <div className="rounded-xl bg-slate-900/40 border border-slate-700/50 px-3 py-2 text-slate-300">Refusals: <span className="text-slate-100">{compact(refusals)}</span></div>
        </div>
        <div className="divide-y divide-slate-700/60">
          {(budgetRows || []).slice(0, 8).map((row) => <BudgetRow key={`${row.tenant_id}-${row.role_id}`} {...row} />)}
          {(!budgetRows || budgetRows.length === 0) && <div className="py-3 text-sm text-slate-500">{budgetEmpty}</div>}
        </div>
      </div>
    </details>
  );
}

function TokenPie({ rows, labelKey }) {
  const data = (rows || [])
    .filter((row) => Number(row.tokens || 0) > 0)
    .slice(0, 8)
    .map((row) => ({ name: row[labelKey] || "unknown", value: Number(row.tokens || 0) }));
  if (data.length === 0) {
    return <div className="flex h-48 items-center justify-center text-sm text-slate-500">No token usage recorded</div>;
  }
  return (
    <div className="h-48">
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie data={data} dataKey="value" nameKey="name" innerRadius={42} outerRadius={72} paddingAngle={2}>
            {data.map((entry, index) => <Cell key={entry.name} fill={PIE_COLORS[index % PIE_COLORS.length]} />)}
          </Pie>
          <Tooltip formatter={(value) => compact(value)} />
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}

function TokenRows({ rows, labelKey }) {
  return (
    <ul className="space-y-2">
      {(rows || []).slice(0, 10).map((row) => (
        <li key={row[labelKey]} className="rounded-xl border border-slate-700/50 bg-slate-900/35 px-3 py-2 text-sm">
          <div className="flex items-center justify-between gap-3">
            <span className="text-slate-300 truncate">{row[labelKey] || "unknown"}</span>
            <span className="text-slate-100 font-mono">{compact(row.tokens)} tokens</span>
          </div>
          <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-slate-500">
            <span>{compact(row.requests || 0)} requests</span>
            <span>Budget {available(row.budget_tokens) ? `${compact(row.budget_tokens)} tokens` : "not configured"}</span>
            <span>Burn {pct(row.utilization_pct)}</span>
          </div>
        </li>
      ))}
      {(!rows || rows.length === 0) && <li className="text-sm text-slate-500">No records for this month</li>}
    </ul>
  );
}

function TokenDimension({ title, rows, labelKey }) {
  return (
    <details className="rounded-2xl border border-slate-700/60 bg-slate-800/70" open>
      <summary className="flex cursor-pointer list-none items-center justify-between gap-4 px-5 py-4">
        <div>
          <h2 className="text-sm font-semibold text-slate-200">{title}</h2>
          <p className="mt-1 text-xs text-slate-500">{compact((rows || []).reduce((sum, row) => sum + Number(row.tokens || 0), 0))} tokens</p>
        </div>
        <span className="rounded-lg border border-slate-700 px-2.5 py-1 text-xs text-slate-300">Toggle</span>
      </summary>
      <div className="grid grid-cols-1 lg:grid-cols-[240px_1fr] gap-4 border-t border-slate-700/60 px-5 pb-5 pt-4">
        <TokenPie rows={rows} labelKey={labelKey} />
        <TokenRows rows={rows} labelKey={labelKey} />
      </div>
    </details>
  );
}

function TokenBreakdown({ tokens }) {
  return (
    <section className="space-y-3">
      <div>
        <h2 className="text-sm font-semibold text-slate-200">Token Breakdown</h2>
        <p className="mt-1 text-xs text-slate-500">Monthly usage and derived budgets from real chat/model activity.</p>
      </div>
      <TokenDimension title="Monthly tokens by tenant" rows={tokens.by_tenant} labelKey="tenant_id" />
      <TokenDimension title="Monthly tokens by team" rows={tokens.by_team} labelKey="team_id" />
      <TokenDimension title="Monthly tokens by role" rows={tokens.by_role} labelKey="role_id" />
      <TokenDimension title="Monthly tokens by user" rows={tokens.by_user} labelKey="user_email" />
    </section>
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
              <th className="py-2 pr-4">Team</th>
              <th className="py-2 pr-4">Role</th>
              <th className="py-2 pr-4">Model</th>
              <th className="py-2 pr-4">Tokens</th>
              <th className="py-2 pr-4">Source</th>
              <th className="py-2">Budget</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-700/50">
            {(events || []).slice(0, 25).map((row, index) => (
              <tr key={`${row.trace_id}-${index}`} className="text-slate-300">
                <td className="py-2 pr-4 text-xs text-slate-500">{row.timestamp ? new Date(row.timestamp).toLocaleTimeString() : "No data"}</td>
                <td className="py-2 pr-4 font-mono text-xs text-slate-400 truncate max-w-[180px]">{row.trace_id}</td>
                <td className="py-2 pr-4">{row.tenant_id}</td>
                <td className="py-2 pr-4">{row.team_id || "unknown"}</td>
                <td className="py-2 pr-4">{row.role}</td>
                <td className="py-2 pr-4">{row.model || row.provider || "No data"}</td>
                <td className="py-2 pr-4 text-slate-400">{compact(row.total_tokens)}</td>
                <td className="py-2 pr-4 text-slate-400">{row.token_source || "unmetered"}</td>
                <td className="py-2 text-slate-400">{row.budget_status || "No data"}</td>
              </tr>
            ))}
            {(!events || events.length === 0) && (
              <tr><td colSpan={9} className="py-4 text-slate-500">No FinOps events in this month</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

export default function FinOps() {
  const { theme } = useTheme();
  const chart = chartTheme(theme);
  const [summary, setSummary] = useState(null);
  const [month, setMonth] = useState(currentMonthKey());
  const [err, setErr] = useState("");

  async function load(targetMonth = month) {
    setErr("");
    try {
      const qs = new URLSearchParams({ month: targetMonth });
      const data = await api(`/admin/finops/summary?${qs.toString()}`);
      setSummary(data);
    } catch (e) {
      setErr(String(e.message || e));
    }
  }

  useEffect(() => { load(month); }, [month]);

  const fin = summary?.summary || {};
  const tokens = summary?.token_breakdown || {};
  const budgets = summary?.budget_governance || {};
  const budgetRows = budgets.daily_budgets || [];
  const meteringNotice = fin.metering_notice;
  const budgetEmpty = budgets.event_count
    ? "Budget checks recorded, but no token budgets are configured for scoped roles"
    : "No budget checks recorded yet";
  const tokenByHour = (tokens.by_hour || []).map((row) => ({
    hour: row.hour ? new Date(row.hour).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "unknown",
    tokens: Number(row.tokens || 0),
  }));
  const sourceCounts = Object.entries(tokens.token_source_counts || {}).map(([source, count]) => `${source}: ${compact(count)}`).join(" · ");

  return (
    <div className="space-y-5">
      {err && <div className="error">{err}</div>}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-lg font-semibold text-slate-100">FinOps</h1>
          <div className="text-xs text-slate-500">
            {summary?.scope?.admin_scope === "tenant" ? `Tenant scope: ${summary.scope.tenant_id}` : "Platform scope"}
            {summary?.period?.month ? ` · ${summary.period.month} month-to-date` : ""}
          </div>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          <input
            type="month"
            value={month}
            onChange={(event) => setMonth(event.target.value || currentMonthKey())}
            className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200"
            aria-label="FinOps month"
          />
          <button type="button" onClick={() => load(month)} className="inline-flex items-center gap-2 rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200 hover:bg-slate-700">
            <RefreshCw className="h-4 w-4" /> Refresh
          </button>
        </div>
      </div>

      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-slate-200">Executive FinOps</h2>
        <div className="grid grid-cols-1 md:grid-cols-3 xl:grid-cols-6 gap-4">
          {available(fin.requests_recorded) && <MetricCard title="Requests recorded" value={fin.requests_recorded} icon={Activity} color="blue" />}
          {available(fin.model_routed_requests) && <MetricCard title="Model routed" value={fin.model_routed_requests} icon={Gauge} color="violet" />}
          {available(fin.tokens_month_to_date ?? fin.tokens_today) && <MetricCard title="Tokens month-to-date" value={fin.tokens_month_to_date ?? fin.tokens_today} icon={Hash} color="blue" />}
          {available(fin.budget_utilization_pct) && <MetricCard title="Budget utilization" value={fin.budget_utilization_pct} unit="%" icon={Gauge} color={fin.budget_utilization_pct > 85 ? "rose" : fin.budget_utilization_pct > 60 ? "amber" : "emerald"} />}
          {available(fin.budget_refusals) && <MetricCard title="Budget refusals" value={fin.budget_refusals} icon={ShieldX} color="amber" />}
          {available(budgets.unmetered_count) && <MetricCard title="Unmetered requests" value={budgets.unmetered_count} icon={Activity} color="violet" />}
        </div>
        {meteringNotice && (
          <div className="rounded-xl border border-slate-700/60 bg-slate-900/40 px-3 py-2 text-sm text-slate-400">
            {meteringNotice}
          </div>
        )}
        {sourceCounts && <div className="text-xs text-slate-500">{sourceCounts}</div>}
      </section>

      <BudgetGovernance budgets={budgets} fin={fin} budgetRows={budgetRows} budgetEmpty={budgetEmpty} />

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <Panel title="Token activity by hour">
          <div className="h-56">
            {tokenByHour.length ? (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={tokenByHour} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={chart.grid} />
                  <XAxis dataKey="hour" stroke={chart.axis} fontSize={11} />
                  <YAxis stroke={chart.axis} fontSize={11} />
                  <Tooltip contentStyle={chart.tooltip} formatter={(value) => compact(value)} />
                  <Bar dataKey="tokens" fill={chart.bar} radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="flex h-full items-center justify-center text-sm text-slate-500">No hourly token records yet</div>
            )}
          </div>
        </Panel>
        <Panel title="Model and provider routing">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm">
            {(tokens.by_provider || []).slice(0, 6).map((row) => (
              <div key={row.provider} className="rounded-xl bg-slate-900/40 border border-slate-700/50 px-3 py-2 text-slate-300">
                <span className="text-slate-500">Provider</span>
                <div className="mt-1 flex justify-between gap-3"><span>{row.provider}</span><span>{compact(row.tokens)}</span></div>
              </div>
            ))}
            {(tokens.by_model || []).slice(0, 6).map((row) => (
              <div key={row.model} className="rounded-xl bg-slate-900/40 border border-slate-700/50 px-3 py-2 text-slate-300">
                <span className="text-slate-500">Model</span>
                <div className="mt-1 flex justify-between gap-3"><span className="truncate">{row.model}</span><span>{compact(row.tokens)}</span></div>
              </div>
            ))}
            {(!tokens.by_provider || tokens.by_provider.length === 0) && (!tokens.by_model || tokens.by_model.length === 0) && (
              <div className="text-sm text-slate-500">No model routing records for this month</div>
            )}
          </div>
        </Panel>
      </div>

      <TokenBreakdown tokens={tokens} />

      <RecentFinOpsEvents events={summary?.recent_events || []} />
    </div>
  );
}
