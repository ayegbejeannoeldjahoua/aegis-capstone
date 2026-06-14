import React from "react";

export default function EmptyState({ title, hint, icon: Icon }) {
  return (
    <div className="flex flex-col items-center justify-center py-10 text-slate-400">
      {Icon && <Icon className="h-8 w-8 mb-3 text-slate-500" />}
      <div className="text-sm font-medium">{title}</div>
      {hint && <div className="text-xs text-slate-500 mt-1">{hint}</div>}
    </div>
  );
}
