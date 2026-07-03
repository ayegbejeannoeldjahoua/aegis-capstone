import React from "react";
import { Moon, Sun } from "lucide-react";
import { useTheme } from "./useTheme.js";

export default function ThemeToggle({ compact = false }) {
  const { theme, setTheme } = useTheme();
  const isLight = theme === "light";

  return (
    <div className="theme-toggle" role="group" aria-label="Theme">
      <button
        type="button"
        className={!isLight ? "active" : ""}
        aria-pressed={!isLight}
        title="Use dark mode"
        onClick={() => setTheme("dark")}
      >
        <Moon size={compact ? 12 : 13} />
        {!compact && <span>Dark</span>}
      </button>
      <button
        type="button"
        className={isLight ? "active" : ""}
        aria-pressed={isLight}
        title="Use light mode"
        onClick={() => setTheme("light")}
      >
        <Sun size={compact ? 12 : 13} />
        {!compact && <span>Light</span>}
      </button>
    </div>
  );
}
