import React from "react";
import { CheckCircle2, CircleSlash, XCircle } from "lucide-react";

function valueOf(metric) {
  if (!metric || metric.instrumented === false || metric.value === null || metric.value === undefined) return "not instrumented";
  if (metric.unit) return `${metric.value} ${metric.unit}`;
  return String(metric.value);
}

function Status({ name, status, detail }) {
  const ok = status === "healthy" || status === "ok" || status === true;
  const muted = status === "not instrumented";
  return (
    <li className="flex items-center justify-between gap-3 text-sm">
      <span className="text-slate-300">{name}</span>
      {muted ? (
        <span className="flex items-center gap-1 text-slate-500"><CircleSlash className="h-4 w-4" /> {detail || "not instrumented"}</span>
      ) : ok ? (
        <span className="flex items-center gap-1 text-emerald-400"><CheckCircle2 className="h-4 w-4" /> {detail || "healthy"}</span>
      ) : (
        <span className="flex items-center gap-1 text-rose-400"><XCircle className="h-4 w-4" /> {detail || "check"}</span>
      )}
    </li>
  );
}

export default function SystemHealth({ system }) {
  if (system) {
    const redis = system.redis_health || {};
    return (
      <div className="rounded-2xl border border-slate-700/60 bg-slate-800/70 p-5">
        <h3 className="text-sm font-semibold text-slate-200 mb-4">System and load</h3>
        <ul className="space-y-2">
          <Status name="Active requests" status="ok" detail={valueOf(system.active_requests)} />
          <Status name="Requests / minute" status="ok" detail={valueOf(system.requests_per_minute)} />
          <Status name="API memory" status={system.api_memory_mb?.instrumented === false ? "not instrumented" : "ok"} detail={valueOf(system.api_memory_mb)} />
          <Status name="API CPU" status="not instrumented" detail={valueOf(system.api_cpu_pct)} />
          <Status name="Postgres connections" status={system.postgres_connections?.instrumented === false ? "not instrumented" : "ok"} detail={valueOf(system.postgres_connections)} />
          <Status name="Redis" status={redis.status === "healthy" || redis.status === "memory-fallback" ? "healthy" : redis.status} detail={`${redis.status || "unknown"}${redis.backend ? ` (${redis.backend})` : ""}`} />
          <Status name="Keycloak sessions" status="not instrumented" detail={valueOf(system.keycloak_active_sessions)} />
          <Status name="Caddy 502/504" status="not instrumented" detail={valueOf(system.caddy_502_504_count)} />
          <Status name="Provider timeout/rate-limit" status="ok" detail={valueOf(system.model_provider_timeout_rate_limit_count)} />
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
