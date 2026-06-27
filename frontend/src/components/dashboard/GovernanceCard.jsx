import React from "react";
import { Ban, EyeOff, FileWarning, KeyRound, ShieldCheck, ShieldX, Target, UserX, Wand2 } from "lucide-react";
import MetricCard from "./MetricCard.jsx";

export default function GovernanceCard({ governance }) {
  const allow = governance?.policy_allow_rate_pct?.value ?? 0;
  const leakage = governance?.cross_tenant_leakage_alerts?.value ?? 0;
  return (
    <section className="space-y-3">
      <h2 className="text-sm font-semibold text-slate-200">Governance correctness</h2>
      <div className="grid grid-cols-1 md:grid-cols-3 xl:grid-cols-5 gap-4">
        <MetricCard title="Policy allow rate" value={governance?.policy_allow_rate_pct}
                    icon={ShieldCheck} color={allow >= 95 ? "emerald" : allow >= 80 ? "amber" : "rose"} />
        <MetricCard title="Policy deny count" value={governance?.policy_deny_count}
                    icon={ShieldX} color="rose" />
        <MetricCard title="Refusal rate" value={governance?.refusal_rate_pct}
                    icon={UserX} color="amber" />
        <MetricCard title="PII redactions applied" value={governance?.pii_redactions_applied}
                    icon={EyeOff} color="violet" />
        <MetricCard title="Trace coverage" value={governance?.trace_coverage_pct}
                    icon={Target} color="blue" />
        <MetricCard title="ISA pass rate" value={governance?.isa_pass_rate_pct}
                    icon={ShieldCheck} color="emerald" />
        <MetricCard title="Budget refusals" value={governance?.budget_refusals}
                    icon={Ban} color="amber" />
        <MetricCard title="Prompt-injection findings" value={governance?.prompt_injection_findings}
                    icon={Wand2} color="rose" />
        <MetricCard title="Cross-tenant leakage alerts" value={governance?.cross_tenant_leakage_alerts}
                    icon={FileWarning} color={leakage === 0 ? "emerald" : "rose"} />
        <MetricCard title="Access posture" value={leakage === 0 ? "isolated" : "alert"}
                    icon={KeyRound} color={leakage === 0 ? "emerald" : "rose"} />
      </div>
    </section>
  );
}
