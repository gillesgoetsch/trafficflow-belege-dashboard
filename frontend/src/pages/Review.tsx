import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { useUi } from "../store/ui";
import type { Provider, ReviewItem } from "../types";
import { Card } from "../components/ui/card";
import { Button } from "../components/ui/button";
import { Badge } from "../components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select";
import { fmtRelative } from "../lib/format";
import { Check, X, ArrowRight, ListChecks } from "lucide-react";
import { ReceiptDetailPanel } from "../components/receipts/ReceiptDetailPanel";
import { toast } from "../components/ui/toaster";

export default function Review() {
  const orgId = useUi((s) => s.selectedOrgId);
  const qc = useQueryClient();
  const [openId, setOpenId] = useState<number | null>(null);
  const [focus, setFocus] = useState(0);

  const { data: items } = useQuery<ReviewItem[]>({
    queryKey: ["review", orgId],
    queryFn: () => api("/review", { query: { organization_id: orgId ?? undefined } }),
  });
  const { data: providers } = useQuery<Provider[]>({ queryKey: ["providers"], queryFn: () => api("/providers") });

  const decide = useMutation({
    mutationFn: ({ id, body }: { id: number; body: any }) =>
      api(`/review/${id}/decide`, { method: "POST", body }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["review"] }); qc.invalidateQueries({ queryKey: ["receipts"] }); toast({ title: "Updated", variant: "success" }); },
    onError: (e: any) => toast({ title: "Failed", description: e.message, variant: "destructive" }),
  });

  useEffect(() => {
    const fn = (e: KeyboardEvent) => {
      if (!items?.length) return;
      const tgt = e.target as HTMLElement;
      if (tgt && (tgt.tagName === "INPUT" || tgt.tagName === "TEXTAREA")) return;
      const cur = items[focus];
      if (!cur) return;
      if (e.key === "j") { setFocus((i) => Math.min(items.length - 1, i + 1)); }
      else if (e.key === "k") { setFocus((i) => Math.max(0, i - 1)); }
      else if (e.key === "Enter") setOpenId(cur.receipt_id);
      else if (e.key === "a" && cur.suggested_provider_id) {
        decide.mutate({ id: cur.receipt_id, body: { action: "accept", provider_id: cur.suggested_provider_id, create_rule: true } });
      }
      else if (e.key === "r") { decide.mutate({ id: cur.receipt_id, body: { action: "reject" } }); }
    };
    window.addEventListener("keydown", fn);
    return () => window.removeEventListener("keydown", fn);
  }, [items, focus, decide]);

  return (
    <div className="p-4 sm:p-6 space-y-4">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2"><ListChecks className="h-5 w-5" /> Review queue</h1>
          <p className="text-sm text-muted-foreground">{items?.length ?? 0} items awaiting decision · <kbd className="px-1 py-0.5 rounded bg-muted text-[10px]">j/k</kbd> navigate · <kbd className="px-1 py-0.5 rounded bg-muted text-[10px]">a</kbd> accept · <kbd className="px-1 py-0.5 rounded bg-muted text-[10px]">r</kbd> reject</p>
        </div>
      </header>

      <div className="space-y-2">
        {(items ?? []).map((it, idx) => (
          <Card key={it.receipt_id} className={focus === idx ? "ring-2 ring-primary/40" : ""}>
            <div className="p-3 flex items-center gap-3">
              <div className="flex-1 min-w-0" onClick={() => { setFocus(idx); setOpenId(it.receipt_id); }} role="button">
                <div className="text-sm font-medium truncate">{it.subject || "(no subject)"}</div>
                <div className="text-xs text-muted-foreground truncate">{it.sender} · {fmtRelative(it.received_at)}</div>
              </div>
              {it.suggested_provider_slug && (
                <Badge variant="secondary" className="hidden sm:inline-flex">{it.suggested_provider_slug} · {Math.round(it.confidence * 100)}%</Badge>
              )}
              {it.reason && <Badge variant="warning" className="hidden md:inline-flex">{it.reason}</Badge>}
              <div className="flex items-center gap-1">
                <ProviderPicker
                  value={it.suggested_provider_id ?? null}
                  providers={providers ?? []}
                  onPick={(pid) => decide.mutate({ id: it.receipt_id, body: { action: "accept", provider_id: pid, create_rule: true } })}
                />
                <Button size="sm" variant="outline" onClick={() => decide.mutate({ id: it.receipt_id, body: { action: "reject" } })}><X className="h-3.5 w-3.5 mr-1" /> Reject</Button>
                {it.suggested_provider_id && (
                  <Button size="sm" onClick={() => decide.mutate({ id: it.receipt_id, body: { action: "accept", provider_id: it.suggested_provider_id, create_rule: true } })}>
                    <Check className="h-3.5 w-3.5 mr-1" /> Accept
                  </Button>
                )}
              </div>
            </div>
          </Card>
        ))}
        {!items?.length && (
          <div className="text-center py-16 text-muted-foreground text-sm">Inbox zero — no items to review.</div>
        )}
      </div>
      <ReceiptDetailPanel id={openId} onClose={() => setOpenId(null)} />
    </div>
  );
}

function ProviderPicker({ value, providers, onPick }: { value: number | null; providers: Provider[]; onPick: (id: number) => void }) {
  return (
    <Select value={value ? String(value) : undefined} onValueChange={(v) => onPick(parseInt(v))}>
      <SelectTrigger className="w-44 h-8 text-xs"><SelectValue placeholder="Assign provider…" /></SelectTrigger>
      <SelectContent>
        {providers.map((p) => <SelectItem key={p.id} value={String(p.id)}>{p.display_name}</SelectItem>)}
      </SelectContent>
    </Select>
  );
}
