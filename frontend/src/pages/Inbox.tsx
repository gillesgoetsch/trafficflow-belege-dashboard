import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, apiBase } from "../lib/api";
import { useUi } from "../store/ui";
import type { Provider, Receipt, ReceiptList } from "../types";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Badge } from "../components/ui/badge";
import { Card } from "../components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select";
import { Download, RefreshCw, Trash2, FilterX } from "lucide-react";
import { fmtDate, fmtMoney } from "../lib/format";
import { ReceiptDetailPanel } from "../components/receipts/ReceiptDetailPanel";
import { toast } from "../components/ui/toaster";

const PAGE_SIZE = 50;

export default function Inbox() {
  const orgId = useUi((s) => s.selectedOrgId);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [providerId, setProviderId] = useState<number | null>(null);
  const [status, setStatus] = useState<string | undefined>(undefined);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [openId, setOpenId] = useState<number | null>(null);
  const [focusIndex, setFocusIndex] = useState(0);
  const qc = useQueryClient();

  useEffect(() => { setPage(1); setSelectedIds(new Set()); }, [orgId, search, providerId, status]);

  const { data: providers } = useQuery<Provider[]>({ queryKey: ["providers"], queryFn: () => api("/providers") });

  const { data, isFetching } = useQuery<ReceiptList>({
    queryKey: ["receipts", { orgId, page, search, providerId, status }],
    queryFn: () => api("/receipts", { query: {
      organization_id: orgId ?? undefined,
      provider_id: providerId ?? undefined,
      status,
      search: search || undefined,
      page, page_size: PAGE_SIZE,
    }}),
  });

  const items = data?.items ?? [];
  const total = data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  // Keyboard nav j/k/Enter
  useEffect(() => {
    const fn = (e: KeyboardEvent) => {
      const tgt = e.target as HTMLElement | null;
      if (tgt && (tgt.tagName === "INPUT" || tgt.tagName === "TEXTAREA")) return;
      if (e.key === "j") { e.preventDefault(); setFocusIndex((i) => Math.min(items.length - 1, i + 1)); }
      else if (e.key === "k") { e.preventDefault(); setFocusIndex((i) => Math.max(0, i - 1)); }
      else if (e.key === "Enter" && items[focusIndex]) { e.preventDefault(); setOpenId(items[focusIndex].id); }
      else if (e.key === "x" && items[focusIndex]) { e.preventDefault(); toggleSelect(items[focusIndex].id); }
    };
    window.addEventListener("keydown", fn);
    return () => window.removeEventListener("keydown", fn);
  }, [items, focusIndex]);

  const toggleSelect = (id: number) => {
    setSelectedIds((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id); else n.add(id);
      return n;
    });
  };

  const bulk = useMutation({
    mutationFn: async (action: "zip" | "reprocess" | "resync" | "delete") => {
      const ids = Array.from(selectedIds);
      if (action === "zip") {
        const res = await fetch(`${apiBase}/receipts/bulk/zip`, {
          method: "POST", credentials: "include",
          headers: { "Content-Type": "application/json", ...(localStorage.getItem("belege_token") ? { Authorization: `Bearer ${localStorage.getItem("belege_token")}` } : {}) },
          body: JSON.stringify({ ids }),
        });
        if (!res.ok) throw new Error("Download failed");
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url; a.download = `receipts-${Date.now()}.zip`;
        a.click(); URL.revokeObjectURL(url);
        return;
      }
      await api(`/receipts/bulk/${action}`, { method: action === "delete" ? "POST" : "POST", body: { ids } });
    },
    onSuccess: (_, action) => {
      toast({ title: `Bulk ${action} ok`, variant: "success" });
      qc.invalidateQueries({ queryKey: ["receipts"] });
      setSelectedIds(new Set());
    },
    onError: (e: any) => toast({ title: "Bulk action failed", description: e.message, variant: "destructive" }),
  });

  return (
    <div className="p-4 sm:p-6 space-y-4">
      <header className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Inbox</h1>
          <p className="text-sm text-muted-foreground">{total} receipts {isFetching && "· refreshing…"}</p>
        </div>
        <div className="flex items-center gap-2">
          {selectedIds.size > 0 && (
            <>
              <span className="text-sm text-muted-foreground">{selectedIds.size} selected</span>
              <Button size="sm" variant="outline" onClick={() => bulk.mutate("zip")}><Download className="h-3.5 w-3.5 mr-1" /> ZIP</Button>
              <Button size="sm" variant="outline" onClick={() => bulk.mutate("reprocess")}><RefreshCw className="h-3.5 w-3.5 mr-1" /> Reprocess</Button>
              <Button size="sm" variant="outline" onClick={() => bulk.mutate("resync")}>Re-sync</Button>
              <Button size="sm" variant="destructive" onClick={() => bulk.mutate("delete")}><Trash2 className="h-3.5 w-3.5 mr-1" /> Delete</Button>
            </>
          )}
        </div>
      </header>

      <Card className="p-3 flex flex-wrap items-center gap-2">
        <Input
          placeholder="Search filename or invoice…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-56"
        />
        <Select value={providerId ? String(providerId) : "all"} onValueChange={(v) => setProviderId(v === "all" ? null : parseInt(v))}>
          <SelectTrigger className="w-48"><SelectValue placeholder="Provider" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All providers</SelectItem>
            {(providers ?? []).map((p) => <SelectItem key={p.id} value={String(p.id)}>{p.display_name}</SelectItem>)}
          </SelectContent>
        </Select>
        <Select value={status ?? "any"} onValueChange={(v) => setStatus(v === "any" ? undefined : v)}>
          <SelectTrigger className="w-44"><SelectValue placeholder="Status" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="any">All statuses</SelectItem>
            <SelectItem value="processed">Processed</SelectItem>
            <SelectItem value="review_needed">Needs review</SelectItem>
            <SelectItem value="archived">Archived</SelectItem>
            <SelectItem value="failed">Failed</SelectItem>
          </SelectContent>
        </Select>
        {(search || providerId || status) && (
          <Button variant="ghost" size="sm" onClick={() => { setSearch(""); setProviderId(null); setStatus(undefined); }}>
            <FilterX className="h-3.5 w-3.5 mr-1" /> Clear
          </Button>
        )}
      </Card>

      <Card className="overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-8"></TableHead>
              <TableHead>Date</TableHead>
              <TableHead>Provider</TableHead>
              <TableHead>Client</TableHead>
              <TableHead>Filename</TableHead>
              <TableHead className="text-right">Amount</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Layer</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((r, idx) => (
              <TableRow
                key={r.id}
                data-state={focusIndex === idx ? "selected" : undefined}
                className="cursor-pointer"
                onClick={(e) => {
                  if (e.shiftKey) toggleSelect(r.id);
                  else { setFocusIndex(idx); setOpenId(r.id); }
                }}
              >
                <TableCell onClick={(e) => { e.stopPropagation(); toggleSelect(r.id); }}>
                  <input type="checkbox" checked={selectedIds.has(r.id)} onChange={() => toggleSelect(r.id)} />
                </TableCell>
                <TableCell className="whitespace-nowrap">{fmtDate(r.document_date)}</TableCell>
                <TableCell>{(providers ?? []).find((p) => p.id === r.provider_id)?.display_name ?? "—"}</TableCell>
                <TableCell>{r.client_id ?? "—"}</TableCell>
                <TableCell className="max-w-[280px] truncate" title={r.filename}>{r.filename}</TableCell>
                <TableCell className="text-right whitespace-nowrap">{fmtMoney(r.amount, r.currency)}</TableCell>
                <TableCell><StatusBadge status={r.status} /></TableCell>
                <TableCell><LayerBadge layer={r.classification_layer} /></TableCell>
              </TableRow>
            ))}
            {!items.length && (
              <TableRow><TableCell colSpan={8} className="text-center text-muted-foreground py-12">No receipts yet</TableCell></TableRow>
            )}
          </TableBody>
        </Table>
      </Card>

      <div className="flex items-center justify-between text-sm">
        <div className="text-muted-foreground">Page {page} of {totalPages}</div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>Previous</Button>
          <Button variant="outline" size="sm" disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>Next</Button>
        </div>
      </div>

      <ReceiptDetailPanel id={openId} onClose={() => setOpenId(null)} />
    </div>
  );
}

function StatusBadge({ status }: { status: Receipt["status"] }) {
  const map: Record<Receipt["status"], { variant: any; label: string }> = {
    processing: { variant: "secondary", label: "Processing" },
    processed: { variant: "success", label: "Processed" },
    review_needed: { variant: "warning", label: "Review" },
    archived: { variant: "outline", label: "Archived" },
    failed: { variant: "destructive", label: "Failed" },
  };
  const c = map[status];
  return <Badge variant={c.variant}>{c.label}</Badge>;
}
function LayerBadge({ layer }: { layer: Receipt["classification_layer"] }) {
  const label = { "1": "Rules", "2": "LLM", "3": "Review", "manual": "Manual" }[layer];
  return <Badge variant="outline">{label}</Badge>;
}
