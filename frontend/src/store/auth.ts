import { create } from "zustand";
import { api } from "../lib/api";
import type { User } from "../types";

type AuthState = {
  user: User | null | undefined; // undefined = unhydrated
  hydrate: () => Promise<void>;
  login: (email: string, password: string, otp?: string) => Promise<void>;
  logout: () => Promise<void>;
};

export const useAuth = create<AuthState>((set) => ({
  user: undefined,
  hydrate: async () => {
    try {
      const u = await api<User>("/auth/me");
      set({ user: u });
    } catch {
      set({ user: null });
    }
  },
  login: async (email, password, otp) => {
    const res = await api<{ access_token: string; user: User }>("/auth/login", {
      method: "POST",
      body: { email, password, otp },
    });
    localStorage.setItem("belege_token", res.access_token);
    set({ user: res.user });
  },
  logout: async () => {
    try { await api("/auth/logout", { method: "POST" }); } catch {}
    localStorage.removeItem("belege_token");
    set({ user: null });
  },
}));
