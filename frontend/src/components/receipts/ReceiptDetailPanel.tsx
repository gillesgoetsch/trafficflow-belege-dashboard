import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, apiBase } from "../../lib/api";
import type { Connector, DocumentType, Organization, PaymentMethod, Provider, ReceiptDetail, Client } from "../../types";
import { DOCUMENT_TYPE_LABEL, PAYMENT_METHOD_LABEL } from "../../types";
import { SyncDetailRow } from "./SyncBadges";
import { Dialog, DialogContent, DialogTitle, DialogDescription } from "../ui/dialog";
import { fmtDate, fmtDateTime, fmtMoney } from "../../lib/format";
import { Button } from "../ui/button";
import { Badge } from "../ui/badge";
import { Input } from "../ui/input";
import { Label } from "../ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../ui/select";
import { RefreshCw, Save, BookCheck, BookX, Download, Loader2, Cloud, Cpu } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "../ui/toaster";
import { Textarea } from "../ui/textarea";
import { PdfPreview } from "./PdfPreview";

export function ReceiptDetailPanel({ id, onClose }: { id: number | null; onClose: () => void }) {
  const qc = useQueryClient();
  const [edit, setEdit] = useState<any>({});

  const { data, isLoading } = useQuery<ReceiptDetail>({
    queryKey: ["receipt", id],
    queryFn: () => api(`/receipts/${id}`),
    enabled: !!id,
  });

  const { data: providers } = useQuery<Provider[]>({ queryKey: ["providers"], queryFn: () => api("/providers") });
  const { data: orgs } = useQuery<Organization[]>({ queryKey: ["orgs"], queryFn: () => api("/organizations") });
  const { data: clients } = useQuery<Client[]>({
    queryKey: ["clients", data?.organization_id],
    queryFn: () => api("/clients", { query: { organization_id: data?.organization_id } }),
    enabled: !!data,
  });
  const { data: connectors } = useQuery<Connector[]>({
    queryKey: ["connectors", data?.organization_id],
    queryFn: () => api("/connectors", { query: { organization_id: data?.organization_id } }),
    enabled: !!data,
  });

  useEffect(() => { setEdit({}); }, [id]);

  const patch = useMutation({
    mutationFn: (body: any) => api<ReceiptDetail>(`/receipts/${id}`, { method: "PATCH", body }),
    onSuccess: () => { toast({ title: "Gespeichert", variant: "success" }); qc.invalidateQueries({ queryKey: ["receipts"] }); qc.invalidateQueries({ queryKey: ["receipt", id] }); setEdit({}); },
    onError: (e: any) => toast({ title: "Speichern fehlgeschlagen", description: e.message, variant: "destructive" }),
  });

  // Polling helper: after enqueueing, watch the receipt's processing_log
  // for a new entry whose timestamp is later than when we triggered. As soon
  // as that appears the worker has run, so we invalidate and clear local edits.
  async function pollUntilUpdated(startedAtIso: string, maxSeconds = 90) {
    const deadline = Date.now() + maxSeconds * 1000;
    while (Date.now() < deadline) {
      try {
        const fresh: ReceiptDetail = await api(`/receipts/${id}`);
        const logs = fresh.processing_log ?? [];
        const last = logs[logs.length - 1] as any;
        const lastTs = last?.ts as string | undefined;
        if (lastTs && lastTs > startedAtIso) {
          setEdit({});
          qc.setQueryData(["receipt", id], fresh);
          qc.invalidateQueries({ queryKey: ["receipts"] });
          return true;
        }
      } catch {
        // ignore transient errors
      }
      await new Promise((r) => setTimeout(r, 2000));
    }
    qc.invalidateQueries({ queryKey: ["receipt", id] });
    qc.invalidateQueries({ queryKey: ["receipts"] });
    return false;
  }

  const reprocessApi = useMutation({
    mutationFn: () => api(`/receipts/${id}/reprocess?engine=api`, { method: "POST" }),
    onMutate: () => ({ startedAt: new Date().toISOString() }),
    onSuccess: async (_data, _vars, ctx) => {
      toast({ title: "Claude-Extraktion gestartet…", description: "Ca. 5–10 Sekunden." });
      const ok = await pollUntilUpdated((ctx as any).startedAt, 60);
      toast({ title: ok ? "Claude-Extraktion abgeschlossen" : "Aktualisierung wird im Hintergrund fortgesetzt", variant: ok ? "success" : "default" });
    },
    onError: (e: any) => toast({ title: "Neuverarbeitung (API) fehlgeschlagen", description: e.message, variant: "destructive" }),
  });

  const reprocessLocal = useMutation({
    mutationFn: () => api(`/receipts/${id}/reprocess?engine=local`, { method: "POST" }),
    onMutate: () => ({ startedAt: new Date().toISOString() }),
    onSuccess: async (_data, _vars, ctx) => {
      toast({ title: "Lokale KI gestartet…", description: "Qwen-3B auf VPS — kann 20–40 Sekunden dauern." });
      const ok = await pollUntilUpdated((ctx as any).startedAt, 180);
      toast({ title: ok ? "Lokale Extraktion abgeschlossen" : "Aktualisierung wird im Hintergrund fortgesetzt", variant: ok ? "success" : "default" });
    },
    onError: (e: any) => toast({ title: "Neuverarbeitung (lokal) fehlgeschlagen", description: e.message, variant: "destructive" }),
  });

  const reprocessBusy = reprocessApi.isPending || reprocessLocal.isPending;

  const book = useMutation({
    mutationFn: () => api(`/receipts/${id}/book`, { method: "POST" }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["receipt", id] }); qc.invalidateQueries({ queryKey: ["receipts"] }); toast({ title: "Als verbucht markiert", variant: "success" }); },
  });
  const unbook = useMutation({
    mutationFn: () => api(`/receipts/${id}/unbook`, { method: "POST" }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["receipt", id] }); qc.invalidateQueries({ queryKey: ["receipts"] }); toast({ title: "Buchung zurückgesetzt" }); },
  });

  return (
    <Dialog open={!!id} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-5xl h-[85vh] grid-cols-2 grid grid-rows-[auto_1fr] p-0">
        {data && (
          <>
            <div className="col-span-2 p-4 pr-12 border-b border-border flex items-center justify-between gap-3 flex-wrap">
              <div className="min-w-0">
                <DialogTitle className="truncate">{data.filename}</DialogTitle>
                <DialogDescription className="text-xs">
                  Empfangen {fmtDateTime(data.received_at)} · Rechnungsdatum {fmtDate(data.document_date)}{data.due_date ? ` · Fällig ${fmtDate(data.due_date)}` : ""}
                  {data.document_type && data.document_type !== "receipt" ? ` · ${DOCUMENT_TYPE_LABEL[data.document_type as DocumentType] || data.document_type}` : ""}
                </DialogDescription>
              </div>
              <div className="flex items-center gap-2 flex-wrap">
                {data.booked_at ? (
                  <Button size="sm" variant="outline" onClick={() => unbook.mutate()}><BookX className="h-3.5 w-3.5 mr-1" /> Buchung zurück</Button>
                ) : (
                  <Button size="sm" onClick={() => book.mutate()}><BookCheck className="h-3.5 w-3.5 mr-1" /> Verbuchen</Button>
                )}
                <Button size="sm" variant="outline" onClick={() => reprocessApi.mutate()} disabled={reprocessBusy} title="Claude API erneut aufrufen (~$0.005, ~5–10 s)">
                  {reprocessApi.isPending ? <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" /> : <Cloud className="h-3.5 w-3.5 mr-1" />}
                  {reprocessApi.isPending ? "API läuft…" : "Neu verarbeiten API"}
                </Button>
                <Button size="sm" variant="outline" onClick={() => reprocessLocal.mutate()} disabled={reprocessBusy} title="Lokale KI auf dem VPS — kostenlos, 20–40 s">
                  {reprocessLocal.isPending ? <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" /> : <Cpu className="h-3.5 w-3.5 mr-1" />}
                  {reprocessLocal.isPending ? "Lokal läuft…" : "Neu verarbeiten lokal"}
                </Button>
                <a href={`${apiBase}/receipts/${data.id}/file`} download={data.filename}>
                  <Button size="sm" variant="outline"><Download className="h-3.5 w-3.5 mr-1" /> Herunterladen</Button>
                </a>
              </div>
            </div>

            <div className="overflow-hidden border-r border-border min-h-[60vh]">
              {/\.pdf$/i.test(data.filename) ? (
                <PdfPreview
                  url={`${apiBase}/receipts/${data.id}/file`}
                  filename={data.filename}
                />
              ) : (
                <div className="h-full w-full overflow-auto bg-muted/30 flex items-start justify-center py-3">
                  <img
                    src={`${apiBase}/receipts/${data.id}/file`}
                    alt={data.filename}
                    className="max-w-full h-auto object-contain"
                  />
                </div>
              )}
            </div>

            <div className="overflow-auto p-4 space-y-4">
              <section>
                <div className="text-xs uppercase tracking-wider text-muted-foreground mb-2">Daten</div>
                <div className="grid grid-cols-2 gap-3">
                  <Field label="Dokumenttyp">
                    <Select value={edit.document_type ?? data.document_type ?? "receipt"} onValueChange={(v) => setEdit((s: any) => ({ ...s, document_type: v }))}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        {(Object.keys(DOCUMENT_TYPE_LABEL) as DocumentType[]).map((d) => (
                          <SelectItem key={d} value={d}>{DOCUMENT_TYPE_LABEL[d]}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </Field>
                  <Field label="Firma">
                    <Select value={String(edit.organization_id ?? data.organization_id)} onValueChange={(v) => setEdit((s: any) => ({ ...s, organization_id: parseInt(v) }))}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        {(orgs ?? []).map((o) => <SelectItem key={o.id} value={String(o.id)}>{o.name}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </Field>
                  <Field label="Anbieter">
                    <Select value={String(edit.provider_id ?? data.provider_id ?? "")} onValueChange={(v) => setEdit((e: any) => ({ ...e, provider_id: parseInt(v) }))}>
                      <SelectTrigger><SelectValue placeholder="—" /></SelectTrigger>
                      <SelectContent>
                        {(providers ?? []).map((p) => <SelectItem key={p.id} value={String(p.id)}>{p.display_name}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </Field>
                  <Field label="Mandant">
                    <Select value={String(edit.client_id ?? data.client_id ?? "")} onValueChange={(v) => setEdit((e: any) => ({ ...e, client_id: parseInt(v) }))}>
                      <SelectTrigger><SelectValue placeholder="—" /></SelectTrigger>
                      <SelectContent>
                        {(clients ?? []).map((c) => <SelectItem key={c.id} value={String(c.id)}>{c.name}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </Field>
                  <Field label="Betrag">
                    <Input value={edit.amount ?? data.amount ?? ""} onChange={(e) => setEdit((s: any) => ({ ...s, amount: e.target.value }))} />
                  </Field>
                  <Field label="Währung">
                    <Input value={edit.currency ?? data.currency ?? ""} onChange={(e) => setEdit((s: any) => ({ ...s, currency: e.target.value.toUpperCase() }))} />
                  </Field>
                  <Field label="Rechnungsdatum">
                    <Input
                      type="date"
                      value={(edit.document_date ?? data.document_date ?? "").slice(0, 10)}
                      onChange={(e) => setEdit((s: any) => ({ ...s, document_date: e.target.value }))}
                      title="Rechnungsdatum — Datum der Rechnungsausstellung. Maßgeblich für die Buchhaltungsperiode."
                    />
                  </Field>
                  <Field label="Fälligkeitsdatum">
                    <Input
                      type="date"
                      value={(edit.due_date ?? data.due_date ?? "").slice(0, 10)}
                      onChange={(e) => setEdit((s: any) => ({ ...s, due_date: e.target.value }))}
                      title="Fälligkeitsdatum — wann die Zahlung fällig ist. Häufig leer bei bereits gezahlten Kreditkartenbelegen."
                    />
                  </Field>
                  <Field label="Rechnungsnr.">
                    <Input value={edit.invoice_number ?? data.invoice_number ?? ""} onChange={(e) => setEdit((s: any) => ({ ...s, invoice_number: e.target.value }))} />
                  </Field>
                  <Field label="Zahlungsmethode">
                    <Select value={edit.payment_method ?? data.payment_method} onValueChange={(v) => setEdit((s: any) => ({ ...s, payment_method: v }))}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        {(Object.keys(PAYMENT_METHOD_LABEL) as PaymentMethod[]).map((p) => (
                          <SelectItem key={p} value={p}>{PAYMENT_METHOD_LABEL[p]}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </Field>
                  <Field label="Marke">
                    <Input value={edit.brand ?? data.brand ?? ""} placeholder="leckker / sichersatt / ..." onChange={(e) => setEdit((s: any) => ({ ...s, brand: e.target.value }))} />
                  </Field>
                  <Field label="MwSt-Satz %">
                    <Input type="number" step="0.1" value={edit.vat_rate ?? data.vat_rate ?? ""} placeholder="z.B. 8.1" onChange={(e) => setEdit((s: any) => ({ ...s, vat_rate: e.target.value }))} />
                  </Field>
                  <Field label="MwSt-Betrag">
                    <Input type="number" step="0.01" value={edit.vat_amount ?? data.vat_amount ?? ""} placeholder="auto / manuell" onChange={(e) => setEdit((s: any) => ({ ...s, vat_amount: e.target.value }))} />
                  </Field>
                  <Field label="Buchhaltungs-Ref.">
                    <Input value={edit.bookkeeping_ref ?? data.bookkeeping_ref ?? ""} placeholder="Bexio-Nr., Buchungsnr.…" onChange={(e) => setEdit((s: any) => ({ ...s, bookkeeping_ref: e.target.value }))} />
                  </Field>
                  <Field label="Status">
                    <Select value={edit.status ?? data.status} onValueChange={(v) => setEdit((s: any) => ({ ...s, status: v }))}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="processed">Verarbeitet</SelectItem>
                        <SelectItem value="review_needed">Prüfung nötig</SelectItem>
                        <SelectItem value="archived">Archiviert</SelectItem>
                      </SelectContent>
                    </Select>
                  </Field>
                  <Field label="Konfidenz">
                    <div className="text-sm h-9 flex items-center px-1">{Math.round(parseFloat(data.confidence) * 100)}%</div>
                  </Field>
                </div>
                <div className="mt-3">
                  <Label className="text-xs">Notizen</Label>
                  <Textarea
                    rows={2}
                    placeholder="Warum diese Ausgabe — Kontext für die Buchhaltung…"
                    value={edit.notes ?? data.notes ?? ""}
                    onChange={(e) => setEdit((s: any) => ({ ...s, notes: e.target.value }))}
                    className="mt-1"
                  />
                </div>
                <Button className="mt-3" size="sm" disabled={!Object.keys(edit).length} onClick={() => patch.mutate(edit)}>
                  <Save className="h-3.5 w-3.5 mr-1" /> Speichern
                </Button>
                {data.booked_at && (
                  <p className="text-[11px] text-muted-foreground mt-2">
                    Verbucht {fmtDateTime(data.booked_at)}{data.bookkeeping_ref ? ` · Ref ${data.bookkeeping_ref}` : ""}
                  </p>
                )}
              </section>

              <section>
                <div className="text-xs uppercase tracking-wider text-muted-foreground mb-2">Sync-Ziele</div>
                <div className="space-y-2">
                  {(data.sync_targets ?? []).map((t) => (
                    <SyncDetailRow
                      key={t.id}
                      target={t}
                      connector={connectors?.find((c) => c.id === t.connector_id)}
                    />
                  ))}
                  {!(data.sync_targets ?? []).length && <p className="text-sm text-muted-foreground">Keine Sync-Ziele konfiguriert.</p>}
                </div>
              </section>

              <section>
                <div className="text-xs uppercase tracking-wider text-muted-foreground mb-2">Verarbeitungsverlauf</div>
                <div className="space-y-1.5 text-xs">
                  {(data.processing_log ?? []).map((entry, i) => (
                    <div key={i} className="rounded border border-border bg-muted/30 p-2 font-mono whitespace-pre-wrap break-words">
                      {JSON.stringify(entry, null, 1)}
                    </div>
                  ))}
                </div>
              </section>
            </div>
          </>
        )}
        {isLoading && <div className="p-6 col-span-2">Wird geladen…</div>}
      </DialogContent>
    </Dialog>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <Label className="text-xs">{label}</Label>
      <div className="mt-1">{children}</div>
    </div>
  );
}
