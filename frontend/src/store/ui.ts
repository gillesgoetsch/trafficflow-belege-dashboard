import { create } from "zustand";

type Theme = "light" | "dark" | "system";

type UiState = {
  paletteOpen: boolean;
  setPaletteOpen: (open: boolean) => void;
  theme: Theme;
  setTheme: (t: Theme) => void;
  toggleTheme: () => void;
  selectedOrgId: number | null;
  setSelectedOrgId: (id: number | null) => void;
};

function readStoredTheme(): Theme {
  if (typeof window === "undefined") return "system";
  const v = localStorage.getItem("belege_theme");
  return v === "light" || v === "dark" || v === "system" ? v : "system";
}

function applyTheme(t: Theme) {
  if (typeof document === "undefined") return;
  const prefersDark =
    typeof window !== "undefined" && window.matchMedia("(prefers-color-scheme: dark)").matches;
  const resolved = t === "system" ? (prefersDark ? "dark" : "light") : t;
  document.documentElement.classList.toggle("dark", resolved === "dark");
}

const storedOrg =
  (typeof window !== "undefined" && parseInt(localStorage.getItem("belege_org") || "")) || null;

export const useUi = create<UiState>((set, get) => ({
  paletteOpen: false,
  setPaletteOpen: (open) => set({ paletteOpen: open }),

  theme: readStoredTheme(),

  setTheme: (t) => {
    localStorage.setItem("belege_theme", t);
    applyTheme(t);
    set({ theme: t });
  },

  // Cycle: system → light → dark → system
  toggleTheme: () => {
    const cur = get().theme;
    const next: Theme = cur === "system" ? "light" : cur === "light" ? "dark" : "system";
    get().setTheme(next);
  },

  selectedOrgId: storedOrg || null,
  setSelectedOrgId: (id) => {
    if (id === null) localStorage.removeItem("belege_org");
    else localStorage.setItem("belege_org", String(id));
    set({ selectedOrgId: id });
  },
}));
