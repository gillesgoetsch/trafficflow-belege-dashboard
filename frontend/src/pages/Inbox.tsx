import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, apiBase } from "../lib/api";
import { useUi } from "../store/ui";
import type { PaymentMethod, Provider, Receipt, ReceiptList } from "../types";
import { PAYMENT_METHOD_LABEL } from "../types";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Badge } from "../components/ui/badge";
import { Card } from "../components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select";
import { Download, RefreshCw, Trash2, FilterX, FileSpreadsheet, BookCheck, Eye } from "lucide-react";
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
  const [paymentMethod, setPaymentMethod] = useState<PaymentMethod | undefined>(undefined);
  const [brand, setBrand] = useState<string | undefined>(undefined);
  const [booked, setBooked] = useState<string | undefined>(undefined);
  const [datePreset, setDatePreset] = useState<string>("");
  const [dateFrom, setDateFrom] = useState<string>("");
  const [dateTo, setDateTo] = useState<string>("");
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [openId, setOpenId] = useState<number | null>(null);
  const [focusIndex, setFocusIndex] = useState(0);
  const qc = useQueryClient();

  useEffect(() => { setPage(1); setSelectedIds(new Set()); }, [orgId, search, providerId, status, paymentMethod, brand, booked, dateFrom, dateTo]);

  // Date preset → from/to
  useEffect(() => {
    if (!datePreset) return;
    const now = new Date();
    const y = now.getFullYear(), m = now.getMonth();
    const fmt = (d: Date) => d.toISOString().slice(0, 10);
    let from: Date | null = null, to: Date | null = null;
    switch (datePreset) {
      case "this_month": from = new Date(y, m, 1); to = new Date(y, m + 1, 0); break;
      case "last_month": from = new Date(y, m - 1, 1); to = new Date(y, m, 0); break;
      case "this_quarter": { const q = Math.floor(m / 3); from = new Date(y, q * 3, 1); to = new Date(y, q * 3 + 3, 0); break; }
      case "last_quarter": { const q = Math.floor(m / 3) - 1; const ny = q < 0 ? y - 1 : y; const nq = (q + 4) % 4; from = new Date(ny, nq * 3, 1); to = new Date(ny, nq * 3 + 3, 0); break; }
      case "ytd": from = new Date(y, 0, 1); to = now; break;
      case "last_year": from = new Date(y - 1, 0, 1); to = new Date(y - 1, 11, 31); break;
    }
    if (from && to) { setDateFrom(fmt(from)); setDateTo(fmt(to)); }
  }, [datePreset]);

  const { data: providers } = useQuery<Provider[]>({ queryKey: ["providers"], queryFn: () => api("/providers") });

  const queryParams = {
    organization_id: orgId ?? undefined,
    provider_id: providerId ?? undefined,
    status,
    payment_method: paymentMethod,
    brand: brand,
    booked: booked,
    date_from: dateFrom || undefined,
    date_to: dateTo || undefined,
    search: search || undefined,
  };

  const { data, isFetching } = useQuery<ReceiptList>({
    queryKey: ["receipts", { ...queryParams, page }],
    queryFn: () => api("/receipts", { query: { ...queryParams, page, page_size: PAGE_SIZE } }),
  });

  const items = data?.items ?? [];
  const pageTotal = useMemo(() => {
    if (!items.length) return null;
    const sum = items.reduce((acc, r) => acc + (r.amount ? parseFloat(r.amount) : 0), 0);
    return sum > 0 ? sum : null;
  }, [items]);
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

  const tokenHeader = () => ({ ...(localStorage.getItem("belege_token") ? { Authorization: `Bearer ${localStorage.getItem("belege_token")}` } : {}) });

  const downloadBlob = async (path: string, init: RequestInit, fallbackName: string) => {
    const res = await fetch(`${apiBase}${path}`, {
      credentials: "include",
      headers: { ...tokenHeader(), ...(init.headers || {}) },
      ...init,
    });
    if (!res.ok) throw new Error(`Download failed: ${res.status}`);
    // Try to grab filename from Content-Disposition
    const cd = res.headers.get("Content-Disposition") || "";
    const m = /filename="?([^"]+)"?/.exec(cd);
    const name = m?.[1] || fallbackName;
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = name; a.click();
    URL.revokeObjectURL(url);
  };

  const bulk = useMutation({
    mutationFn: async (action: "zip" | "reprocess" | "resync" | "delete" | "book") => {
      const ids = Array.from(selectedIds);
      if (action === "zip") {
        await downloadBlob("/receipts/bulk/zip", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ids }),
        }, `receipts-${Date.now()}.zip`);
        return;
      }
      await api(`/receipts/bulk/${action}`, { method: "POST", body: { ids } });
    },
    onSuccess: (_, action) => {
      toast({ title: `Bulk ${action} ok`, variant: "success" });
      qc.invalidateQueries({ queryKey: ["receipts"] });
      setSelectedIds(new Set());
    },
    onError: (e: any) => toast({ title: "Bulk action failed", description: e.message, variant: "destructive" }),
  });

  // Export filtered set as CSV (server-side filter)
  const exportCsv = async () => {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(queryParams)) {
      if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
    }
    await downloadBlob(`/receipts/export/csv?${qs.toString()}`, { method: "GET" },
      `receipts-${new Date().toISOString().slice(0,10)}.csv`);
  };

  // Export filtered set as ZIP (uses /bulk/zip with all currently-shown IDs across pages)
  const exportZipAll = async () => {
    // Fetch all IDs matching current filters (page through if needed)
    const allIds: number[] = [];
    let p = 1;
    while (true) {
      const r: ReceiptList = await api("/receipts", { query: { ...queryParams, page: p, page_size: 200 } });
      allIds.push(...r.items.map((x) => x.id));
      if (allIds.length >= r.total) break;
      p += 1;
      if (p > 50) break; // safety stop
    }
    if (allIds.length === 0) { toast({ title: "Nothing to export" }); return; }
    await downloadBlob("/receipts/bulk/zip", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids: allIds }),
    }, `receipts-${new Date().toISOString().slice(0,10)}.zip`);
    toast({ title: `Downloaded ${allIds.length} receipts`, variant: "success" });
  };

  return (
    <div className="p-4 sm:p-6 space-y-4">
      <header className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Inbox</h1>
          <p className="text-sm text-muted-foreground">{total} receipts {isFetching && "· refreshing…"}</p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {selectedIds.size > 0 ? (
            <>
              <span className="text-sm text-muted-foreground">{selectedIds.size} selected</span>
              <Button size="sm" variant="outline" onClick={() => bulk.mutate("zip")}><Download className="h-3.5 w-3.5 mr-1" /> ZIP</Button>
              <Button size="sm" variant="outline" onClick={() => bulk.mutate("book")}><BookCheck className="h-3.5 w-3.5 mr-1" /> Mark booked</Button>
              <Button size="sm" variant="outline" onClick={() => bulk.mutate("reprocess")}><RefreshCw className="h-3.5 w-3.5 mr-1" /> Reprocess</Button>
              <Button size="sm" variant="outline" onClick={() => bulk.mutate("resync")}>Re-sync</Button>
              <Button size="sm" variant="destructive" onClick={() => bulk.mutate("delete")}><Trash2 className="h-3.5 w-3.5 mr-1" /> Delete</Button>
            </>
          ) : (
            <>
              <Button size="sm" variant="outline" onClick={exportCsv}><FileSpreadsheet className="h-3.5 w-3.5 mr-1" /> Export CSV</Button>
              <Button size="sm" variant="outline" onClick={exportZipAll}><Download className="h-3.5 w-3.5 mr-1" /> Download all (ZIP)</Button>
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
        <Select value={paymentMethod ?? "any"} onValueChange={(v) => setPaymentMethod(v === "any" ? undefined : v as PaymentMethod)}>
          <SelectTrigger className="w-44"><SelectValue placeholder="Payment method" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="any">All payments</SelectItem>
            {(Object.keys(PAYMENT_METHOD_LABEL) as PaymentMethod[]).map((p) => (
              <SelectItem key={p} value={p}>{PAYMENT_METHOD_LABEL[p]}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={brand ?? "any"} onValueChange={(v) => setBrand(v === "any" ? undefined : v)}>
          <SelectTrigger className="w-36"><SelectValue placeholder="Brand" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="any">All brands</SelectItem>
            <SelectItem value="leckker">Leckker</SelectItem>
            <SelectItem value="sichersatt">SicherSatt</SelectItem>
            <SelectItem value="trafficflow">TrafficFlow</SelectItem>
          </SelectContent>
        </Select>
        <Select value={booked ?? "any"} onValueChange={(v) => setBooked(v === "any" ? undefined : v)}>
          <SelectTrigger className="w-36"><SelectValue placeholder="Booked" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="any">All</SelectItem>
            <SelectItem value="no">Open (not booked)</SelectItem>
            <SelectItem value="yes">Booked</SelectItem>
          </SelectContent>
        </Select>
        <Select value={datePreset} onValueChange={setDatePreset}>
          <SelectTrigger className="w-40"><SelectValue placeholder="Date range" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="this_month">This month</SelectItem>
            <SelectItem value="last_month">Last month</SelectItem>
            <SelectItem value="this_quarter">This quarter</SelectItem>
            <SelectItem value="last_quarter">Last quarter</SelectItem>
            <SelectItem value="ytd">Year to date</SelectItem>
            <SelectItem value="last_year">Last year</SelectItem>
          </SelectContent>
        </Select>
        <Input type="date" value={dateFrom} onChange={(e) => { setDateFrom(e.target.value); setDatePreset(""); }} className="w-36" title="From" />
        <Input type="date" value={dateTo} onChange={(e) => { setDateTo(e.target.value); setDatePreset(""); }} className="w-36" title="To" />
        {(search || providerId || status || paymentMethod || brand || booked || dateFrom || dateTo) && (
          <Button variant="ghost" size="sm" onClick={() => { setSearch(""); setProviderId(null); setStatus(undefined); setPaymentMethod(undefined); setBrand(undefined); setBooked(undefined); setDateFrom(""); setDateTo(""); setDatePreset(""); }}>
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
              <TableHead>Brand</TableHead>
              <TableHead>Filename</TableHead>
              <TableHead className="text-right">Amount</TableHead>
              <TableHead>Payment</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Booked</TableHead>
              <TableHead className="w-24"></TableHead>
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
                <TableCell>{r.brand ? <Badge variant="outline">{r.brand}</Badge> : "—"}</TableCell>
                <TableCell className="max-w-[260px] truncate" title={r.filename}>{r.filename}</TableCell>
                <TableCell className="text-right whitespace-nowrap">{fmtMoney(r.amount, r.currency)}</TableCell>
                <TableCell><PaymentBadge pm={r.payment_method} /></TableCell>
                <TableCell><StatusBadge status={r.status} /></TableCell>
                <TableCell>{r.booked_at ? <Badge variant="success">booked</Badge> : <span className="text-muted-foreground text-xs">open</span>}</TableCell>
                <TableCell onClick={(e) => e.stopPropagation()}>
                  <div className="flex items-center gap-0.5">
                    <a href={`${apiBase}/receipts/${r.id}/file`} target="_blank" rel="noreferrer" title="Preview">
                      <Button size="icon" variant="ghost" className="h-7 w-7"><Eye className="h-3.5 w-3.5" /></Button>
                    </a>
                    <a href={`${apiBase}/receipts/${r.id}/file`} download={r.filename} title="Download">
                      <Button size="icon" variant="ghost" className="h-7 w-7"><Download className="h-3.5 w-3.5" /></Button>
                    </a>
                  </div>
                </TableCell>
              </TableRow>
            ))}
            {!items.length && (
              <TableRow><TableCell colSpan={10} className="text-center text-muted-foreground py-12">No receipts match the current filters</TableCell></TableRow>
            )}
          </TableBody>
        </Table>
      </Card>

      <div className="flex items-center justify-between text-sm flex-wrap gap-2">
        <div className="text-muted-foreground">
          Page {page} of {totalPages} · {total} total
          {pageTotal !== null && (
            <span className="ml-3">
              Page sum: <span className="font-mono text-foreground">{fmtMoney(pageTotal, items[0]?.currency || "CHF")}</span>
            </span>
          )}
        </div>
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
function PaymentBadge({ pm }: { pm: PaymentMethod }) {
  const colorMap: Record<PaymentMethod, "default" | "secondary" | "outline"> = {
    credit_card: "default",
    bank_transfer: "secondary",
    twint: "default",
    cash: "outline",
    paypal: "secondary",
    other: "outline",
    unknown: "outline",
  };
  return <Badge variant={colorMap[pm] ?? "outline"}>{PAYMENT_METHOD_LABEL[pm]}</Badge>;
}
