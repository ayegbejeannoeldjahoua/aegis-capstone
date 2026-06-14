import React from "react";

const VARIANT = {
  allow:   "bg-emerald-500/15 text-emerald-300 border border-emerald-500/30",
  deny:    "bg-rose-500/15 text-rose-300 border border-rose-500/30",
  info:    "bg-blue-500/15 text-blue-300 border border-blue-500/30",
  warn:    "bg-amber-500/15 text-amber-300 border border-amber-500/30",
  neutral: "bg-slate-500/15 text-slate-300 border border-slate-500/30",
};

export default function Badge({ variant = "neutral", children }) {
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-medium ${VARIANT[variant] || VARIANT.neutral}`}>
      {children}
    </span>
  );
}
