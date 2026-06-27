import React from "react";
import { FileWarning, KeyRound, ShieldCheck, ShieldX, Target, Wand2 } from "lucide-react";
import MetricCard from "./MetricCard.jsx";

function available(value) {
  return value !== null && value !== undefined;
}

export default function GovernanceCard({ governance }) {
  const allow = governance?.policy_allow_rate ?? 0;
  const leakage = governance?.cross_tenant_leakage_alerts ?? 0;
  const cards = [
    {
      title: "Policy allow rate",
      value: governance?.policy_allow_rate,
      unit: "%",
      icon: ShieldCheck,
      color: allow >= 95 ? "emerald" : allow >= 80 ? "amber" : "rose",
    },
    { title: "Policy deny count", value: governance?.policy_deny_count ?? 0, icon: ShieldX, color: "rose" },
    { title: "Trace coverage", value: governance?.trace_coverage, unit: "%", icon: Target, color: "blue" },
    { title: "ISA pass rate", value: governance?.isa_pass_rate, unit: "%", icon: ShieldCheck, color: "emerald" },
    { title: "Prompt-injection findings", value: governance?.prompt_injection_findings ?? 0, icon: Wand2, color: "rose" },
    {
      title: "Cross-tenant leakage alerts",
      value: governance?.cross_tenant_leakage_alerts,
      icon: FileWarning,
      color: leakage === 0 ? "emerald" : "rose",
    },
    {
      title: "Access posture",
      value: governance?.access_posture || "unknown",
      icon: KeyRound,
      color: governance?.access_posture === "isolated" ? "emerald" : "amber",
    },
  ].filter((card) => available(card.value));

  return (
    <section className="space-y-3">
      <h2 className="text-sm font-semibold text-slate-200">Governance correctness</h2>
      <div className="grid grid-cols-1 md:grid-cols-3 xl:grid-cols-4 gap-4">
        {cards.map((card) => (
          <MetricCard key={card.title} {...card} />
        ))}
      </div>
    </section>
  );
}
