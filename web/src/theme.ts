import { useLayoutEffect, useState } from "react";

export const themes = ["dark", "light", "system"] as const;
export type Theme = typeof themes[number];

const labels: Record<Theme, string> = { dark: "Dark", light: "Light", system: "System" };
const key = "haynes-studio-theme";

function initialTheme(): Theme {
  try {
    const value = window.localStorage.getItem(key);
    return themes.find((theme) => theme === value) ?? "dark";
  } catch {
    return "dark";
  }
}

export function useTheme() {
  const [theme, setTheme] = useState(initialTheme);
  useLayoutEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  function choose(next: Theme) {
    setTheme(next);
    try {
      window.localStorage.setItem(key, next);
    } catch {
      // The in-memory choice still applies for this visit.
    }
  }

  return { theme, choose, labels };
}

export type ThemeSettings = ReturnType<typeof useTheme>;
