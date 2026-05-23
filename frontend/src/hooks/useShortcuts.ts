import { useEffect } from "react";

type Handlers = {
  onOpenPalette: () => void;
  onGoInbox: () => void;
  onGoDashboard: () => void;
  onGoReview: () => void;
  onGoSettings: () => void;
  onGoUpload: () => void;
};

export function useGlobalShortcuts(h: Handlers) {
  useEffect(() => {
    let lastKey = "";
    let lastTs = 0;

    const handle = (e: KeyboardEvent) => {
      const tgt = e.target as HTMLElement | null;
      const editable = tgt && (tgt.tagName === "INPUT" || tgt.tagName === "TEXTAREA" || (tgt as HTMLElement).isContentEditable);

      // Cmd/Ctrl+K — always allowed
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        h.onOpenPalette();
        return;
      }

      if (editable) return;

      // Two-key sequences: g i / g d / g r / g s / g u
      if (e.key === "g") {
        lastKey = "g";
        lastTs = Date.now();
        return;
      }
      if (lastKey === "g" && Date.now() - lastTs < 800) {
        if (e.key === "i") { e.preventDefault(); h.onGoInbox(); }
        else if (e.key === "d") { e.preventDefault(); h.onGoDashboard(); }
        else if (e.key === "r") { e.preventDefault(); h.onGoReview(); }
        else if (e.key === "s") { e.preventDefault(); h.onGoSettings(); }
        else if (e.key === "u") { e.preventDefault(); h.onGoUpload(); }
        lastKey = "";
        return;
      }
      lastKey = "";
    };

    window.addEventListener("keydown", handle);
    return () => window.removeEventListener("keydown", handle);
  }, [h]);
}
