import React, { createContext, useContext, useEffect, useMemo, useState } from "react";
import { applyDocumentTheme, normalizeTheme, readStoredTheme, writeStoredTheme } from "./themeStorage.js";

const ThemeContext = createContext(null);

export function ThemeProvider({ children }) {
  const [theme, setThemeState] = useState(() => readStoredTheme());

  useEffect(() => {
    applyDocumentTheme(theme);
    writeStoredTheme(theme);
  }, [theme]);

  const value = useMemo(() => ({
    theme,
    setTheme(nextTheme) {
      setThemeState(normalizeTheme(nextTheme));
    },
    toggleTheme() {
      setThemeState((current) => current === "light" ? "dark" : "light");
    },
  }), [theme]);

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error("useTheme must be used within ThemeProvider");
  }
  return context;
}
