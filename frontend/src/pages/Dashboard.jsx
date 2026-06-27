import React, { useEffect, useState } from "react";
import { Activity, AlertTriangle, CheckCircle2, CircleDollarSign, Hash, Timer } from "lucide-react";
import { api } from "../api/client.js";
import MetricCard      from "../components/dashboard/MetricCard.jsx";
import SystemHealth    from "../components/dashboard/SystemHealth.jsx";
import ActivityChart   from "../components/dashboard/ActivityChart.jsx";
import GovernanceCard from "../components/dashboard/GovernanceCard.jsx";
import LatencyBreakdownChart from "../components/dashboard/LatencyBreakdownChart.jsx";
import FinOpsSummary from "../components/dashboard/FinOpsSummary.jsx";
import AuditTraceSummary from "../components/dashboard/AuditTraceSummary.jsx";
import RetrievalSummary from "../components/dashboard/RetrievalSummary.jsx";
import RecentDecisionsTable from "../components/dashboard/RecentDecisionsTable.jsx";

export default function Dashboard() {
  const [metrics, setMetrics] = useState(null);
  const [activity, setActivity] = useState([]);
  const [err, setErr] = useState("");

  async function load() {
    setErr("");
    try {
      const m = await api("/admin/dashboard/metrics");
      const a = await api("/admin/dashboard/activity");
      setMetrics(m); setActivity(a.buckets || []);
    } catch (e) { setErr(String(e.message || e)); }
  }
  useEffect(() => { load(); const i = setInterval(load, 15000); return () => clearInterval(i); }, []);

  const summary = metrics?.summary || {};

  return (
    <div className="space-y-5">
      {err && <div className="error">{err}</div>}
      <div className="flex flex-col gap-1">
        <h1 className="text-lg font-semibold text-slate-100">Dashboard</h1>
        <div className="text-xs text-slate-500">
          {metrics?.scope?.admin_scope === "tenant" ? `Tenant scope: ${metrics.scope.tenant_id}` : "Platform scope"}
          {metrics?.generated_at ? ` · generated ${new Date(metrics.generated_at).toLocaleTimeString()}` : ""}
        </div>
      </div>

      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-slate-200">Executive summary</h2>
        <div className="grid grid-cols-1 md:grid-cols-3 xl:grid-cols-6 gap-4">
          <MetricCard title="Requests today" value={summary.requests_today}
                      icon={Activity} color="blue" />
          <MetricCard title="Successful chat turns" value={summary.successful_chat_turns}
                      icon={CheckCircle2} color="emerald" />
          <MetricCard title="Error rate" value={summary.error_rate_pct}
                      icon={AlertTriangle} color={(summary.error_rate_pct?.value || 0) > 5 ? "rose" : "emerald"} />
          <MetricCard title="p95 end-to-end latency" value={summary.p95_e2e_latency_ms}
                      icon={Timer} color="violet" />
          <MetricCard title="Estimated cost today" value={summary.estimated_cost_today_usd}
                      icon={CircleDollarSign} color="amber" />
          <MetricCard title="Tokens today" value={summary.tokens_today}
                      icon={Hash} color="blue" />
        </div>
      </section>

      <GovernanceCard governance={metrics?.governance} />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <ActivityChart data={activity} />
        <SystemHealth system={metrics?.system} />
      </div>

      <LatencyBreakdownChart latency={metrics?.latency} />

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <FinOpsSummary finops={metrics?.finops} />
        <AuditTraceSummary audit={metrics?.audit} />
      </div>

      <RetrievalSummary retrieval={metrics?.retrieval} />
      <RecentDecisionsTable decisions={metrics?.recent_decisions} />
    </div>
  );
}
