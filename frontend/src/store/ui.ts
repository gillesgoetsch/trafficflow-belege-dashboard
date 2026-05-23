import { create } from "zustand";

type UiState = {
  paletteOpen: boolean;
  setPaletteOpen: (open: boolean) => void;
  theme: "dark" | "light";
  toggleTheme: () => void;
  selectedOrgId: number | null;
  setSelectedOrgId: (id: number | null) => void;
};

const stored = (typeof window !== "undefined" && (localStorage.getItem("belege_theme") as "dark" | "light")) || "dark";
const storedOrg = (typeof window !== "undefined" && parseInt(localStorage.getItem("belege_org") || "")) || null;

export const useUi = create<UiState>((set, get) => ({
  paletteOpen: false,
  setPaletteOpen: (open) => set({ paletteOpen: open }),
  theme: stored,
  toggleTheme: () => {
    const next = get().theme === "dark" ? "light" : "dark";
    document.documentElement.classList.toggle("dark", next === "dark");
    localStorage.setItem("belege_theme", next);
    set({ theme: next });
  },
  selectedOrgId: storedOrg || null,
  setSelectedOrgId: (id) => {
    if (id === null) localStorage.removeItem("belege_org");
    else localStorage.setItem("belege_org", String(id));
    set({ selectedOrgId: id });
  },
}));
