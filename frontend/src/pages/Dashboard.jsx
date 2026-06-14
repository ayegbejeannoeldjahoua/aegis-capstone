import React, { useEffect, useState } from "react";
import { Activity, Users, TrendingUp, Zap } from "lucide-react";
import { api } from "../api/client.js";
import MetricCard      from "../components/dashboard/MetricCard.jsx";
import LiveDecisionFeed from "../components/dashboard/LiveDecisionFeed.jsx";
import SystemHealth    from "../components/dashboard/SystemHealth.jsx";
import ActivityChart   from "../components/dashboard/ActivityChart.jsx";

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

  const allowRate = metrics?.allow_rate_pct ?? 0;
  const allowColor = allowRate >= 95 ? "emerald" : allowRate >= 80 ? "amber" : "rose";
  const latency = metrics?.avg_pdp_latency_ms ?? 0;
  const latencyColor = latency < 50 ? "emerald" : latency < 100 ? "amber" : "rose";

  return (
    <div className="space-y-5">
      {err && <div className="error">{err}</div>}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <MetricCard title="Requests today" value={metrics?.total_requests_today ?? 0}
                    icon={Activity} color="blue" trendLabel="all decisions" />
        <MetricCard title="Allow rate" value={allowRate} unit="%"
                    icon={TrendingUp} color={allowColor}
                    trendLabel={allowRate >= 95 ? "healthy" : allowRate >= 80 ? "check denies" : "high deny rate"}
                    trend={allowRate >= 95 ? 1 : allowRate < 80 ? -1 : 0} />
        <MetricCard title="Active tenants" value={metrics?.active_tenants ?? 0}
                    icon={Users} color="blue" trendLabel="tenants with activity" />
        <MetricCard title="Avg PDP latency" value={latency} unit="ms"
                    icon={Zap} color={latencyColor}
                    trendLabel={latency < 50 ? "fast" : latency < 100 ? "ok" : "slow"} />
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <ActivityChart data={activity} />
        <SystemHealth />
      </div>
      <LiveDecisionFeed />
    </div>
  );
}
