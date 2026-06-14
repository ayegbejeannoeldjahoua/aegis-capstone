import React, { useEffect, useState } from "react";
import { CheckCircle2, XCircle, Play } from "lucide-react";
import { api } from "../api/client.js";

const ACTIONS = ["skill.invoke","memory.read","memory.write","tool.call","model.call","runtime.exec","admin.op"];

function isAllowed(action, caps) {
  if (!caps) return false;
  switch (action) {
    case "skill.invoke":  return true;     // open per the new policy
    case "memory.read":   return (caps.readable_namespaces || []).length > 0;
    case "memory.write":  return (caps.writable_namespaces || []).length > 0;
    case "tool.call":     return (caps.tools || []).length > 0;
    case "model.call":    return true;
    case "runtime.exec":  return !!caps.runtime_exec;
    case "admin.op":      return (caps.admin_scope || "none") !== "none";
    default:              return false;
  }
}

export default function PolicyExplorer() {
  const [byTenant, setByTenant] = useState({});
  const [err, setErr] = useState("");

  useEffect(() => {
    api("/admin/policy/capabilities")
      .then(d => setByTenant(d.tenants || {}))
      .catch(e => setErr(String(e.message || e)));
  }, []);

  return (
    <div className="space-y-5">
      {err && <div className="error">{err}</div>}
      <div className="rounded-2xl border border-slate-700/60 bg-slate-800/70 p-5">
        <h3 className="text-sm font-semibold text-slate-200 mb-4">Capability matrix</h3>
        <p className="text-xs text-slate-400 mb-3">Per-role allow/deny across the governed actions.
        Skill invocation is open to all roles (per-skill governance happens via the actions the skill executes).</p>
        {Object.entries(byTenant).map(([tid, roles]) => (
          <div key={tid} className="mb-6">
            <h4 className="text-xs uppercase tracking-wider text-slate-400 mb-2">{tid}</h4>
            <table className="w-full text-sm">
              <thead>
                <tr>
                  <th className="text-left text-xs text-slate-400 py-2 pr-3">role</th>
                  {ACTIONS.map(a => <th key={a} className="text-xs text-slate-400 py-2 px-2 text-center">{a}</th>)}
                </tr>
              </thead>
              <tbody>
                {roles.map(r => (
                  <tr key={r.role_id} className="border-t border-slate-700/40">
                    <td className="py-2 pr-3 text-slate-200 font-medium">{r.role_id}</td>
                    {ACTIONS.map(a => (
                      <td key={a} className="py-2 px-2 text-center">
                        {isAllowed(a, r.capabilities)
                          ? <CheckCircle2 className="inline h-4 w-4 text-emerald-400" />
                          : <XCircle className="inline h-4 w-4 text-slate-600" />}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      </div>
    </div>
  );
}
