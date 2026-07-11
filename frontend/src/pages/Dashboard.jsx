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

function available(value) {
  return value !== null && value !== undefined;
}

function currentMonthKey() {
  return new Date().toISOString().slice(0, 7);
}

export default function Dashboard() {
  const [metrics, setMetrics] = useState(null);
  const [activity, setActivity] = useState([]);
  const [month, setMonth] = useState(currentMonthKey());
  const [err, setErr] = useState("");

  async function load() {
    setErr("");
    try {
      const qs = new URLSearchParams({ month });
      const m = await api(`/admin/dashboard/metrics?${qs.toString()}`);
      const a = await api("/admin/dashboard/activity");
      setMetrics(m); setActivity(a.buckets || []);
    } catch (e) { setErr(String(e.message || e)); }
  }
  useEffect(() => { load(); const i = setInterval(load, 15000); return () => clearInterval(i); }, [month]);

  const summary = metrics?.summary || {};

  return (
    <div className="space-y-5">
      {err && <div className="error">{err}</div>}
      <div className="flex flex-col gap-1">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h1 className="text-lg font-semibold text-slate-100">Dashboard</h1>
          </div>
          <input
            type="month"
            value={month}
            onChange={(event) => setMonth(event.target.value || currentMonthKey())}
            className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200"
            aria-label="Dashboard month"
          />
        </div>
      </div>

      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-slate-200">Executive summary</h2>
        <div className="grid grid-cols-1 md:grid-cols-3 xl:grid-cols-6 gap-4">
          <MetricCard title="Requests MTD" value={summary.requests_month_to_date ?? summary.requests_today ?? 0}
                      icon={Activity} color="blue" />
          <MetricCard title="Successful chat turns" value={summary.successful_chat_turns_month_to_date ?? summary.successful_chat_turns ?? 0}
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
