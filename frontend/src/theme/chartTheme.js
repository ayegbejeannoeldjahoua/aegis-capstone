export function chartTheme() {
  return {
    grid: "var(--chart-grid)",
    axis: "var(--chart-axis)",
    tooltip: {
      background: "var(--chart-tooltip-bg)",
      border: "1px solid var(--chart-tooltip-border)",
      borderRadius: 8,
      color: "var(--text)",
      boxShadow: "var(--chart-tooltip-shadow)",
    },
    allow: "var(--chart-allow)",
    deny: "var(--chart-deny)",
    bar: "var(--chart-bar)",
    cost: "var(--chart-cost)",
  };
}
