import React, { useEffect, useState } from "react";
import { Activity, AlertTriangle, Building2, CheckCircle2, KeyRound, Timer } from "lucide-react";
import { api } from "../api/client.js";
import MetricCard      from "../components/dashboard/MetricCard.jsx";
import SystemHealth    from "../components/dashboard/SystemHealth.jsx";
import ActivityChart   from "../components/dashboard/ActivityChart.jsx";
import GovernanceCard from "../components/dashboard/GovernanceCard.jsx";
import LatencyBreakdownChart from "../components/dashboard/LatencyBreakdownChart.jsx";
import AuditTraceSummary from "../components/dashboard/AuditTraceSummary.jsx";
import RetrievalSummary from "../components/dashboard/RetrievalSummary.jsx";
import RecentDecisionsTable from "../components/dashboard/RecentDecisionsTable.jsx";
import InstrumentationGapsPanel from "../components/dashboard/InstrumentationGapsPanel.jsx";

function available(value) {
  return value !== null && value !== undefined;
}

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
          <MetricCard title="Requests today" value={summary.requests_today ?? 0}
                      icon={Activity} color="blue" />
          <MetricCard title="Successful chat turns" value={summary.successful_chat_turns ?? 0}
                      icon={CheckCircle2} color="emerald" />
          {available(summary.error_rate) && (
            <MetricCard title="Error rate" value={summary.error_rate}
                        unit="%" icon={AlertTriangle} color={(summary.error_rate || 0) > 5 ? "rose" : "emerald"} />
          )}
          {available(summary.p95_end_to_end_latency_ms) && (
            <MetricCard title="p95 end-to-end latency" value={summary.p95_end_to_end_latency_ms}
                        unit="ms" icon={Timer} color="violet" />
          )}
          <MetricCard title="Active tenants" value={summary.active_tenants ?? metrics?.active_tenants ?? 0}
                      icon={Building2} color="blue" />
          <MetricCard title="Access posture" value={summary.access_posture || "unknown"}
                      icon={KeyRound} color={summary.access_posture === "isolated" ? "emerald" : "amber"} />
        </div>
      </section>

      <GovernanceCard governance={metrics?.governance} />
      <InstrumentationGapsPanel gaps={metrics?.instrumentation_gaps || []} />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <ActivityChart data={activity} />
        <SystemHealth system={metrics?.system} />
      </div>

      <LatencyBreakdownChart latency={metrics?.latency} />

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <AuditTraceSummary audit={metrics?.audit} />
        <RetrievalSummary retrieval={metrics?.retrieval} />
      </div>

      <RecentDecisionsTable decisions={metrics?.recent_decisions} />
    </div>
  );
}
