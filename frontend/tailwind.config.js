/** @type {import('tailwindcss').Config} */
//
// Aegis frontend Tailwind config — v3 (3.4.4).
//
// Two palettes live here:
//
//   1. The existing dark-slate Aegis palette is defined directly in
//      src/styles.css and used by hand-authored components (.card, .stat,
//      .bubble, …). It does not require Tailwind-utility access.
//
//   2. The Figma design-system palette (Phase A token migration, see
//      src/tokens.css) is exposed below as Tailwind utility classes so
//      migrated pages can use `bg-primary`, `text-foreground`, `bg-card`,
//      `border-border`, `rounded-md`, etc. These utilities resolve to the
//      CSS variables defined in tokens.css, which only have values inside
//      a `.theme-figma` subtree. Outside that subtree the utility falls
//      back to "unset" — harmless because no current component references
//      these utility names.
//
// To use the Figma utilities on a page:
//
//      <div className="theme-figma min-h-screen bg-background text-foreground">
//        ...
//      </div>
//
// Reference: the variable names below are the exact set from the
// Figma Make export (Project Aegis, 2026-06-25).
//
export default {
  content: ["./index.html", "./src/**/*.{js,jsx,ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Figma surface tones
        background: "var(--background)",
        foreground: "var(--foreground)",

        // Cards / popovers (DEFAULT + foreground sub-key works as
        // bg-card / text-card-foreground in Tailwind v3)
        card: {
          DEFAULT: "var(--card)",
          foreground: "var(--card-foreground)",
        },
        popover: {
          DEFAULT: "var(--popover)",
          foreground: "var(--popover-foreground)",
        },

        // Primary brand (dark navy on the Aegis sign-in card)
        primary: {
          DEFAULT: "var(--primary)",
          foreground: "var(--primary-foreground)",
        },
        secondary: {
          DEFAULT: "var(--secondary)",
          foreground: "var(--secondary-foreground)",
        },
        muted: {
          DEFAULT: "var(--muted)",
          foreground: "var(--muted-foreground)",
        },
        accent: {
          DEFAULT: "var(--accent)",
          foreground: "var(--accent-foreground)",
        },
        destructive: {
          DEFAULT: "var(--destructive)",
          foreground: "var(--destructive-foreground)",
        },

        // Form controls
        border: "var(--border)",
        input: {
          DEFAULT: "var(--input)",
          background: "var(--input-background)",
        },
        ring: "var(--ring)",

        // Recharts palette via CSS vars (shadcn/ui chart.tsx convention)
        chart: {
          1: "var(--chart-1)",
          2: "var(--chart-2)",
          3: "var(--chart-3)",
          4: "var(--chart-4)",
          5: "var(--chart-5)",
        },

        // Sidebar palette
        sidebar: {
          DEFAULT: "var(--sidebar)",
          foreground: "var(--sidebar-foreground)",
          primary: "var(--sidebar-primary)",
          "primary-foreground": "var(--sidebar-primary-foreground)",
          accent: "var(--sidebar-accent)",
          "accent-foreground": "var(--sidebar-accent-foreground)",
          border: "var(--sidebar-border)",
          ring: "var(--sidebar-ring)",
        },
      },

      borderRadius: {
        sm: "var(--radius-sm)",
        md: "var(--radius-md)",
        lg: "var(--radius-lg)",
        xl: "var(--radius-xl)",
      },

      fontWeight: {
        normal: "var(--font-weight-normal)",
        medium: "var(--font-weight-medium)",
      },
    },
  },
  plugins: [],
}
