import * as React from "react";
import * as ToastPrimitives from "@radix-ui/react-toast";
import { X } from "lucide-react";
import { cn } from "../../lib/utils";
import { create } from "zustand";

type Toast = { id: string; title?: string; description?: string; variant?: "default" | "destructive" | "success" };
type ToastState = {
  toasts: Toast[];
  push: (t: Omit<Toast, "id">) => void;
  dismiss: (id: string) => void;
};
export const useToast = create<ToastState>((set) => ({
  toasts: [],
  push: (t) => {
    const id = Math.random().toString(36).slice(2);
    set((s) => ({ toasts: [...s.toasts, { ...t, id }] }));
    setTimeout(() => set((s) => ({ toasts: s.toasts.filter((x) => x.id !== id) })), 4500);
  },
  dismiss: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
}));

export function toast(t: Omit<Toast, "id">) {
  useToast.getState().push(t);
}

export function Toaster() {
  const toasts = useToast((s) => s.toasts);
  const dismiss = useToast((s) => s.dismiss);
  return (
    <ToastPrimitives.Provider swipeDirection="right">
      {toasts.map((t) => (
        <ToastPrimitives.Root
          key={t.id}
          className={cn(
            "data-[state=open]:animate-slide-in fixed bottom-4 right-4 z-[100] flex w-[360px] items-start gap-3 rounded-md border p-3 shadow-lg",
            t.variant === "destructive"
              ? "border-destructive/30 bg-destructive/10 text-destructive"
              : t.variant === "success"
              ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
              : "border-border bg-card text-card-foreground"
          )}
        >
          <div className="flex-1">
            {t.title && <ToastPrimitives.Title className="text-sm font-medium">{t.title}</ToastPrimitives.Title>}
            {t.description && <ToastPrimitives.Description className="text-xs opacity-80 mt-0.5">{t.description}</ToastPrimitives.Description>}
          </div>
          <ToastPrimitives.Close onClick={() => dismiss(t.id)} className="opacity-70 hover:opacity-100">
            <X className="h-4 w-4" />
          </ToastPrimitives.Close>
        </ToastPrimitives.Root>
      ))}
      <ToastPrimitives.Viewport />
    </ToastPrimitives.Provider>
  );
}
