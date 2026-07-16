import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, apiBase } from "../lib/api";
import { useUi } from "../store/ui";
import type { Connector, PaymentMethod, Provider, Receipt, ReceiptList } from "../types";
import { PAYMENT_METHOD_LABEL } from "../types";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Badge } from "../components/ui/badge";
import { Card } from "../components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select";
import { Download, RefreshCw, Trash2, FilterX, FileSpreadsheet, BookCheck, Eye, Loader2, Cloud, Cpu, ArrowUp, ArrowDown, ChevronsUpDown } from "lucide-react";
import { fmtDate, fmtMoney } from "../lib/format";
import { ReceiptDetailPanel } from "../components/receipts/ReceiptDetailPanel";
import { SyncRowIcons } from "../components/receipts/SyncBadges";
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
  const [dateField, setDateField] = useState<"document_date" | "received_at">("document_date");
  const [sortColumn, setSortColumn] = useState<string>("document_date");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [openId, setOpenId] = useState<number | null>(null);
  const [focusIndex, setFocusIndex] = useState(0);
  const [zipBusy, setZipBusy] = useState(false);
  const [selectingAll, setSelectingAll] = useState(false);
  const qc = useQueryClient();

  useEffect(() => { setPage(1); setSelectedIds(new Set()); }, [orgId, search, providerId, status, paymentMethod, brand, booked, dateFrom, dateTo]);

  // Date preset → from/to
  useEffect(() => {
    if (!datePreset) return;
    const now = new Date();
    const y = now.getFullYear(), m = now.getMonth();
    const fmt = (d: Date) => d.toISOString().slice(0, 10);
    let from: Date | null = null, to: Date | null = null;
    const quarterRange = (yr: number, q: number) => [new Date(yr, q * 3, 1), new Date(yr, q * 3 + 3, 0)];
    switch (datePreset) {
      case "this_month": from = new Date(y, m, 1); to = new Date(y, m + 1, 0); break;
      case "last_month": from = new Date(y, m - 1, 1); to = new Date(y, m, 0); break;
      case "this_quarter": [from, to] = quarterRange(y, Math.floor(m / 3)); break;
      case "last_quarter": {
        const q = Math.floor(m / 3) - 1;
        const ny = q < 0 ? y - 1 : y;
        const nq = (q + 4) % 4;
        [from, to] = quarterRange(ny, nq);
        break;
      }
      case "q1_thisyear": [from, to] = quarterRange(y, 0); break;
      case "q2_thisyear": [from, to] = quarterRange(y, 1); break;
      case "q3_thisyear": [from, to] = quarterRange(y, 2); break;
      case "q4_thisyear": [from, to] = quarterRange(y, 3); break;
      case "q1_lastyear": [from, to] = quarterRange(y - 1, 0); break;
      case "q2_lastyear": [from, to] = quarterRange(y - 1, 1); break;
      case "q3_lastyear": [from, to] = quarterRange(y - 1, 2); break;
      case "q4_lastyear": [from, to] = quarterRange(y - 1, 3); break;
      case "ytd": from = new Date(y, 0, 1); to = now; break;
      case "this_year": from = new Date(y, 0, 1); to = new Date(y, 11, 31); break;
      case "last_year": from = new Date(y - 1, 0, 1); to = new Date(y - 1, 11, 31); break;
    }
    if (from && to) { setDateFrom(fmt(from)); setDateTo(fmt(to)); }
  }, [datePreset]);

  const { data: providers } = useQuery<Provider[]>({ queryKey: ["providers"], queryFn: () => api("/providers") });
  const { data: connectors } = useQuery<Connector[]>({
    queryKey: ["connectors", orgId],
    queryFn: () => api("/connectors", { query: { organization_id: orgId ?? undefined } }),
  });

  const queryParams = {
    organization_id: orgId ?? undefined,
    provider_id: providerId ?? undefined,
    status,
    payment_method: paymentMethod,
    brand: brand,
    booked: booked,
    date_from: dateFrom || undefined,
    date_to: dateTo || undefined,
    date_field: dateField,
    search: search || undefined,
    sort: sortColumn,
    order: sortDir,
  };

  const toggleSort = (col: string) => {
    if (sortColumn === col) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortColumn(col);
      setSortDir("desc");
    }
  };
  const sortIcon = (col: string) => {
    if (sortColumn !== col) return <ChevronsUpDown className="h-3 w-3 opacity-30 inline ml-1" />;
    return sortDir === "asc" ? <ArrowUp className="h-3 w-3 inline ml-1" /> : <ArrowDown className="h-3 w-3 inline ml-1" />;
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

  // Fetch every receipt id matching the current filters (paging through ALL
  // pages, not just the visible one). Used by the header select-all + export.
  const fetchAllFilteredIds = async (): Promise<number[]> => {
    const allIds: number[] = [];
    let p = 1;
    while (true) {
      const r: ReceiptList = await api("/receipts", { query: { ...queryParams, page: p, page_size: 200 } });
      allIds.push(...r.items.map((x) => x.id));
      if (allIds.length >= r.total || r.items.length === 0) break;
      p += 1;
      if (p > 100) break; // safety stop
    }
    return allIds;
  };

  // Header checkbox: select ALL receipts matching the current filter across all
  // pages (so a bulk ZIP/export covers the whole set), or clear when full.
  const toggleSelectAll = async () => {
    const allSelected = total > 0 && selectedIds.size >= total;
    if (allSelected) { setSelectedIds(new Set()); return; }
    setSelectingAll(true);
    try {
      const ids = await fetchAllFilteredIds();
      setSelectedIds(new Set(ids));
      if (ids.length > items.length) toast({ title: `${ids.length} Belege ausgewählt (alle Seiten)` });
    } finally {
      setSelectingAll(false);
    }
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
        setZipBusy(true);
        try {
          await downloadBlob("/receipts/bulk/zip", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ ids }),
          }, `receipts-${Date.now()}.zip`);
        } finally {
          setZipBusy(false);
        }
        return;
      }
      await api(`/receipts/bulk/${action}`, { method: "POST", body: { ids } });
    },
    onSuccess: (_, action) => {
      const labels: Record<string, string> = {
        zip: "ZIP heruntergeladen",
        reprocess: "Neu verarbeitet",
        resync: "Synchronisiert",
        delete: "Gelöscht",
        book: "Als verbucht markiert",
      };
      toast({ title: labels[action] || "Aktion ausgeführt", variant: "success" });
      qc.invalidateQueries({ queryKey: ["receipts"] });
      setSelectedIds(new Set());
    },
    onError: (e: any) => toast({ title: "Massenaktion fehlgeschlagen", description: e.message, variant: "destructive" }),
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
    setZipBusy(true);
    try {
      const allIds = await fetchAllFilteredIds();
      if (allIds.length === 0) { toast({ title: "Keine Belege zum Exportieren" }); return; }
      await downloadBlob("/receipts/bulk/zip", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ids: allIds }),
      }, `receipts-${new Date().toISOString().slice(0,10)}.zip`);
      toast({ title: `${allIds.length} Belege heruntergeladen`, variant: "success" });
    } finally {
      setZipBusy(false);
    }
  };

  return (
    <div className="p-4 sm:p-6 space-y-4">
      <header className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Belege</h1>
          <p className="text-sm text-muted-foreground">{total} Belege {isFetching && "· wird aktualisiert…"}</p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {selectedIds.size > 0 ? (
            <>
              <span className="text-sm text-muted-foreground">{selectedIds.size} ausgewählt</span>
              <Button size="sm" variant="outline" onClick={() => bulk.mutate("zip")} disabled={zipBusy}>
                {zipBusy ? <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" /> : <Download className="h-3.5 w-3.5 mr-1" />}
                {zipBusy ? "ZIP wird erstellt…" : "ZIP"}
              </Button>
              <Button size="sm" variant="outline" onClick={() => bulk.mutate("book")}><BookCheck className="h-3.5 w-3.5 mr-1" /> Verbuchen</Button>
              <Button size="sm" variant="outline" onClick={() => bulk.mutate("reprocess")}><RefreshCw className="h-3.5 w-3.5 mr-1" /> Neu verarbeiten</Button>
              <Button size="sm" variant="outline" onClick={() => bulk.mutate("resync")}>Erneut synchronisieren</Button>
              <Button size="sm" variant="destructive" onClick={() => bulk.mutate("delete")}><Trash2 className="h-3.5 w-3.5 mr-1" /> Löschen</Button>
            </>
          ) : (
            <>
              <Button size="sm" variant="outline" onClick={exportCsv}><FileSpreadsheet className="h-3.5 w-3.5 mr-1" /> CSV exportieren</Button>
              <Button size="sm" variant="outline" onClick={exportZipAll} disabled={zipBusy}>
                {zipBusy ? <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" /> : <Download className="h-3.5 w-3.5 mr-1" />}
                {zipBusy ? "ZIP wird erstellt…" : "Alle herunterladen (ZIP)"}
              </Button>
            </>
          )}
        </div>
      </header>

      <Card className="p-3 flex flex-wrap items-center gap-2">
        <Input
          placeholder="Dateiname oder Rechnungsnr. suchen…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-56"
        />
        <Select value={providerId ? String(providerId) : "all"} onValueChange={(v) => setProviderId(v === "all" ? null : parseInt(v))}>
          <SelectTrigger className="w-48"><SelectValue placeholder="Anbieter" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Alle Anbieter</SelectItem>
            {(providers ?? []).map((p) => <SelectItem key={p.id} value={String(p.id)}>{p.display_name}</SelectItem>)}
          </SelectContent>
        </Select>
        <Select value={status ?? "any"} onValueChange={(v) => setStatus(v === "any" ? undefined : v)}>
          <SelectTrigger className="w-44"><SelectValue placeholder="Status" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="any">Alle Status</SelectItem>
            <SelectItem value="processed">Verarbeitet</SelectItem>
            <SelectItem value="review_needed">Prüfung nötig</SelectItem>
            <SelectItem value="archived">Archiviert</SelectItem>
            <SelectItem value="failed">Fehlgeschlagen</SelectItem>
          </SelectContent>
        </Select>
        <Select value={paymentMethod ?? "any"} onValueChange={(v) => setPaymentMethod(v === "any" ? undefined : v as PaymentMethod)}>
          <SelectTrigger className="w-44"><SelectValue placeholder="Zahlungsmethode" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="any">Alle Zahlungsarten</SelectItem>
            {(Object.keys(PAYMENT_METHOD_LABEL) as PaymentMethod[]).map((p) => (
              <SelectItem key={p} value={p}>{PAYMENT_METHOD_LABEL[p]}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={brand ?? "any"} onValueChange={(v) => setBrand(v === "any" ? undefined : v)}>
          <SelectTrigger className="w-36"><SelectValue placeholder="Marke" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="any">Alle Marken</SelectItem>
            <SelectItem value="leckker">Leckker</SelectItem>
            <SelectItem value="sichersatt">SicherSatt</SelectItem>
            <SelectItem value="trafficflow">TrafficFlow</SelectItem>
          </SelectContent>
        </Select>
        <Select value={booked ?? "any"} onValueChange={(v) => setBooked(v === "any" ? undefined : v)}>
          <SelectTrigger className="w-36"><SelectValue placeholder="Verbucht" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="any">Alle</SelectItem>
            <SelectItem value="no">Offen (nicht verbucht)</SelectItem>
            <SelectItem value="yes">Verbucht</SelectItem>
          </SelectContent>
        </Select>
        <Select value={datePreset} onValueChange={setDatePreset}>
          <SelectTrigger className="w-44"><SelectValue placeholder="Zeitraum" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="this_month">Dieser Monat</SelectItem>
            <SelectItem value="last_month">Letzter Monat</SelectItem>
            <SelectItem value="this_quarter">Dieses Quartal</SelectItem>
            <SelectItem value="last_quarter">Letztes Quartal</SelectItem>
            <SelectItem value="q1_thisyear">Q1 (dieses Jahr)</SelectItem>
            <SelectItem value="q2_thisyear">Q2 (dieses Jahr)</SelectItem>
            <SelectItem value="q3_thisyear">Q3 (dieses Jahr)</SelectItem>
            <SelectItem value="q4_thisyear">Q4 (dieses Jahr)</SelectItem>
            <SelectItem value="ytd">Jahr bis heute</SelectItem>
            <SelectItem value="this_year">Dieses Jahr</SelectItem>
            <SelectItem value="last_year">Letztes Jahr</SelectItem>
            <SelectItem value="q1_lastyear">Q1 (letztes Jahr)</SelectItem>
            <SelectItem value="q2_lastyear">Q2 (letztes Jahr)</SelectItem>
            <SelectItem value="q3_lastyear">Q3 (letztes Jahr)</SelectItem>
            <SelectItem value="q4_lastyear">Q4 (letztes Jahr)</SelectItem>
          </SelectContent>
        </Select>
        <Select value={dateField} onValueChange={(v) => setDateField(v as any)}>
          <SelectTrigger className="w-44" title="Welches Datum wird gefiltert">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="document_date">Filter: Rechnungsdatum</SelectItem>
            <SelectItem value="received_at">Filter: Scan-/Eingangsdatum</SelectItem>
          </SelectContent>
        </Select>
        <Input type="date" value={dateFrom} onChange={(e) => { setDateFrom(e.target.value); setDatePreset(""); }} className="w-36" title="Von" />
        <Input type="date" value={dateTo} onChange={(e) => { setDateTo(e.target.value); setDatePreset(""); }} className="w-36" title="Bis" />
        {(search || providerId || status || paymentMethod || brand || booked || dateFrom || dateTo) && (
          <Button variant="ghost" size="sm" onClick={() => { setSearch(""); setProviderId(null); setStatus(undefined); setPaymentMethod(undefined); setBrand(undefined); setBooked(undefined); setDateFrom(""); setDateTo(""); setDatePreset(""); setDateField("document_date"); }}>
            <FilterX className="h-3.5 w-3.5 mr-1" /> Zurücksetzen
          </Button>
        )}
      </Card>

      <Card className="overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-8">
                <input
                  type="checkbox"
                  className="h-4 w-4 cursor-pointer accent-primary align-middle disabled:opacity-40"
                  aria-label="Alle passenden Belege auswählen"
                  title={selectedIds.size > 0 ? "Auswahl aufheben" : "Alle passenden Belege auswählen (über alle Seiten)"}
                  disabled={selectingAll || total === 0}
                  ref={(el) => { if (el) el.indeterminate = selectedIds.size > 0 && selectedIds.size < total; }}
                  checked={total > 0 && selectedIds.size >= total}
                  onChange={toggleSelectAll}
                />
              </TableHead>
              <TableHead onClick={() => toggleSort("document_date")} className="cursor-pointer select-none whitespace-nowrap" title="Rechnungsdatum (vom Dokument selbst)">
                Rechnungsdatum{sortIcon("document_date")}
              </TableHead>
              <TableHead onClick={() => toggleSort("received_at")} className="cursor-pointer select-none whitespace-nowrap" title="Wann eingegangen / hochgeladen">
                Empfangen{sortIcon("received_at")}
              </TableHead>
              <TableHead onClick={() => toggleSort("provider_id")} className="cursor-pointer select-none whitespace-nowrap">
                Anbieter{sortIcon("provider_id")}
              </TableHead>
              <TableHead onClick={() => toggleSort("brand")} className="cursor-pointer select-none whitespace-nowrap">
                Marke{sortIcon("brand")}
              </TableHead>
              <TableHead onClick={() => toggleSort("filename")} className="cursor-pointer select-none whitespace-nowrap">
                Dateiname{sortIcon("filename")}
              </TableHead>
              <TableHead onClick={() => toggleSort("amount")} className="cursor-pointer select-none whitespace-nowrap text-right">
                Betrag{sortIcon("amount")}
              </TableHead>
              <TableHead onClick={() => toggleSort("payment_method")} className="cursor-pointer select-none whitespace-nowrap">
                Zahlung{sortIcon("payment_method")}
              </TableHead>
              <TableHead onClick={() => toggleSort("status")} className="cursor-pointer select-none whitespace-nowrap">
                Status{sortIcon("status")}
              </TableHead>
              <TableHead className="select-none w-20 whitespace-nowrap" title="Sync-Status pro Connector — Klick öffnet den Inspector">
                Sync
              </TableHead>
              <TableHead onClick={() => toggleSort("booked_at")} className="cursor-pointer select-none whitespace-nowrap">
                Verbucht{sortIcon("booked_at")}
              </TableHead>
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
                <TableCell
                  className="w-8"
                  onClick={(e) => { e.stopPropagation(); toggleSelect(r.id); }}
                >
                  <input
                    type="checkbox"
                    className="h-4 w-4 cursor-pointer accent-primary"
                    checked={selectedIds.has(r.id)}
                    onClick={(e) => e.stopPropagation()}
                    onChange={(e) => { e.stopPropagation(); toggleSelect(r.id); }}
                  />
                </TableCell>
                <TableCell className="whitespace-nowrap">{fmtDate(r.document_date)}</TableCell>
                <TableCell className="whitespace-nowrap text-muted-foreground text-xs">{fmtDate(r.received_at)}</TableCell>
                <TableCell>{(providers ?? []).find((p) => p.id === r.provider_id)?.display_name ?? "—"}</TableCell>
                <TableCell>{r.brand ? <Badge variant="outline">{r.brand}</Badge> : "—"}</TableCell>
                <TableCell className="max-w-[260px] truncate" title={r.filename}>{r.filename}</TableCell>
                <TableCell className="text-right whitespace-nowrap">{fmtMoney(r.amount, r.currency)}</TableCell>
                <TableCell><PaymentBadge pm={r.payment_method} /></TableCell>
                <TableCell><StatusBadge status={r.status} /></TableCell>
                <TableCell>
                  <SyncRowIcons targets={r.sync_targets ?? []} connectors={connectors} />
                </TableCell>
                <TableCell>{r.booked_at ? <Badge variant="success">verbucht</Badge> : <span className="text-muted-foreground text-xs">offen</span>}</TableCell>
                <TableCell onClick={(e) => e.stopPropagation()}>
                  <div className="flex items-center gap-0.5">
                    <Button size="icon" variant="ghost" className="h-7 w-7" title="Vorschau" onClick={() => { setFocusIndex(idx); setOpenId(r.id); }}>
                      <Eye className="h-3.5 w-3.5" />
                    </Button>
                    <RowReprocessButton receiptId={r.id} engine="api" />
                    <RowReprocessButton receiptId={r.id} engine="local" />
                    <a href={`${apiBase}/receipts/${r.id}/file`} download={r.filename} title="Herunterladen">
                      <Button size="icon" variant="ghost" className="h-7 w-7"><Download className="h-3.5 w-3.5" /></Button>
                    </a>
                  </div>
                </TableCell>
              </TableRow>
            ))}
            {!items.length && (
              <TableRow><TableCell colSpan={12} className="text-center text-muted-foreground py-12">Keine Belege entsprechen den Filtern</TableCell></TableRow>
            )}
          </TableBody>
        </Table>
      </Card>

      <div className="flex items-center justify-between text-sm flex-wrap gap-2">
        <div className="text-muted-foreground">
          Seite {page} von {totalPages} · {total} insgesamt
          {pageTotal !== null && (
            <span className="ml-3">
              Seitensumme: <span className="font-mono text-foreground">{fmtMoney(pageTotal, items[0]?.currency || "CHF")}</span>
            </span>
          )}
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>Zurück</Button>
          <Button variant="outline" size="sm" disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>Weiter</Button>
        </div>
      </div>

      <ReceiptDetailPanel id={openId} onClose={() => setOpenId(null)} />
    </div>
  );
}

function StatusBadge({ status }: { status: Receipt["status"] }) {
  const map: Record<Receipt["status"], { variant: any; label: string }> = {
    processing: { variant: "secondary", label: "Verarbeitung" },
    processed: { variant: "success", label: "Verarbeitet" },
    review_needed: { variant: "warning", label: "Prüfung" },
    archived: { variant: "outline", label: "Archiviert" },
    failed: { variant: "destructive", label: "Fehler" },
  };
  const c = map[status];
  return <Badge variant={c.variant}>{c.label}</Badge>;
}
function LayerBadge({ layer }: { layer: Receipt["classification_layer"] }) {
  const label = { "1": "Regeln", "2": "KI", "3": "Prüfung", "manual": "Manuell" }[layer];
  return <Badge variant="outline">{label}</Badge>;
}
function RowReprocessButton({ receiptId, engine }: { receiptId: number; engine: "api" | "local" }) {
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);
  const label = engine === "api" ? "Claude API (~$0.005)" : "Lokale KI (kostenlos)";
  const Icon = engine === "api" ? Cloud : Cpu;
  const trigger = async (e: { stopPropagation: () => void }) => {
    e.stopPropagation();
    if (busy) return;
    setBusy(true);
    try {
      const startedAt = new Date().toISOString();
      await api(`/receipts/${receiptId}/reprocess?engine=${engine}`, { method: "POST" });
      toast({ title: engine === "api" ? "Claude-Extraktion gestartet…" : "Lokale KI gestartet…" });
      const deadline = Date.now() + (engine === "api" ? 60_000 : 180_000);
      while (Date.now() < deadline) {
        await new Promise((r) => setTimeout(r, 2500));
        try {
          const fresh: any = await api(`/receipts/${receiptId}`);
          const logs = fresh.processing_log ?? [];
          const last = logs[logs.length - 1];
          if (last?.ts && last.ts > startedAt) {
            qc.invalidateQueries({ queryKey: ["receipts"] });
            qc.invalidateQueries({ queryKey: ["receipt", receiptId] });
            toast({ title: engine === "api" ? "Claude-Extraktion abgeschlossen" : "Lokale Extraktion abgeschlossen", variant: "success" });
            return;
          }
        } catch { /* ignore */ }
      }
      qc.invalidateQueries({ queryKey: ["receipts"] });
    } catch (err: any) {
      toast({ title: "Fehlgeschlagen", description: err.message, variant: "destructive" });
    } finally {
      setBusy(false);
    }
  };
  return (
    <Button size="icon" variant="ghost" className="h-7 w-7" title={label} onClick={trigger} disabled={busy}>
      {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Icon className="h-3.5 w-3.5" />}
    </Button>
  );
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
