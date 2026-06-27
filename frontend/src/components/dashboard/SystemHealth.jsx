import React from "react";
import { CheckCircle2, XCircle } from "lucide-react";

function valueOf(metric) {
  if (metric && typeof metric === "object" && Object.prototype.hasOwnProperty.call(metric, "value")) {
    if (metric.value === null || metric.value === undefined) return "No data";
    if (metric.unit) return `${metric.value} ${metric.unit}`;
    return String(metric.value);
  }
  if (metric === null || metric === undefined) return "No data";
  return String(metric);
}

function Status({ name, status, detail }) {
  const ok = status === "healthy" || status === "ok" || status === true;
  return (
    <li className="flex items-center justify-between gap-3 text-sm">
      <span className="text-slate-300">{name}</span>
      {ok ? (
        <span className="flex items-center gap-1 text-emerald-400"><CheckCircle2 className="h-4 w-4" /> {detail || "healthy"}</span>
      ) : (
        <span className="flex items-center gap-1 text-rose-400"><XCircle className="h-4 w-4" /> {detail || "check"}</span>
      )}
    </li>
  );
}

export default function SystemHealth({ system }) {
  if (system) {
    const health = system.health || {};
    const redis = health.redis || {};
    const postgres = health.postgres || {};
    const provider = health.model_provider || {};
    return (
      <div className="rounded-2xl border border-slate-700/60 bg-slate-800/70 p-5">
        <h3 className="text-sm font-semibold text-slate-200 mb-4">System and load</h3>
        <ul className="space-y-2">
          <Status name="Active requests" status="ok" detail={valueOf(system.active_requests)} />
          <Status name="Requests / minute" status="ok" detail={valueOf(system.requests_per_minute)} />
          <Status name="API memory" status="ok" detail={system.api_memory_mb == null ? "No data" : `${valueOf(system.api_memory_mb)} MB`} />
          <Status name="Postgres" status={postgres.status === "healthy" ? "healthy" : "check"} detail={system.postgres_connections == null ? postgres.status : `${system.postgres_connections} connections`} />
          <Status name="Redis" status={redis.status === "healthy" || redis.status === "memory-fallback" ? "healthy" : redis.status} detail={`${redis.status || "unknown"}${redis.backend ? ` (${redis.backend})` : ""}`} />
          <Status name="Model provider" status={provider.status === "degraded" ? "check" : "healthy"} detail={`${valueOf(system.model_provider_timeout_rate_limit_count)} timeout/rate-limit`} />
        </ul>
      </div>
    );
  }
  const services = [
    { name: "FastAPI",   ok: true },
    { name: "PostgreSQL",ok: true },
    { name: "OPA",       ok: true },
    { name: "Keycloak",  ok: true },
    { name: "Vault",     ok: true },
    { name: "OTel",      ok: true },
  ];
  return (
    <div className="rounded-2xl border border-slate-700/60 bg-slate-800/70 p-5">
      <h3 className="text-sm font-semibold text-slate-200 mb-4">System Health</h3>
      <ul className="space-y-2">
        {services.map((s) => (
          <li key={s.name} className="flex items-center justify-between text-sm">
            <span className="text-slate-300">{s.name}</span>
            {s.ok
              ? <span className="flex items-center gap-1 text-emerald-400"><CheckCircle2 className="h-4 w-4" /> healthy</span>
              : <span className="flex items-center gap-1 text-rose-400"><XCircle className="h-4 w-4" /> down</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}
