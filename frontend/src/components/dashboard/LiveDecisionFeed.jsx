import React, { useEffect, useState } from "react";
import { api } from "../../api/client.js";
import Badge from "../common/Badge.jsx";

export default function LiveDecisionFeed() {
  const [events, setEvents] = useState([]);
  async function load() {
    try {
      const r = await api("/audit/last?limit=14");
      setEvents(r.events || []);
    } catch { /* ignore */ }
  }
  useEffect(() => { load(); const i = setInterval(load, 10000); return () => clearInterval(i); }, []);
  return (
    <div className="rounded-2xl border border-slate-700/60 bg-slate-800/70 p-5">
      <h3 className="text-sm font-semibold text-slate-200 mb-3">Live decisions</h3>
      <ul className="space-y-2 max-h-72 overflow-auto">
        {events.length === 0 && <li className="text-xs text-slate-500">no events yet</li>}
        {events.map((e, i) => (
          <li key={i} className="flex items-center gap-2 text-xs">
            <Badge variant={e.decision === "allow" ? "allow" : "deny"}>{e.decision}</Badge>
            <span className="font-mono text-slate-400">{(e.action || "").padEnd(13, " ")}</span>
            <span className="text-slate-300 truncate">{e.subject_id || ""}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
