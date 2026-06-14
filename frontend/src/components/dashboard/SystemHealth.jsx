import React from "react";
import { CheckCircle2, XCircle } from "lucide-react";

export default function SystemHealth() {
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
