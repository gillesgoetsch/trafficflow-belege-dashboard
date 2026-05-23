import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, apiBase } from "../../lib/api";
import type { PaymentMethod, Provider, ReceiptDetail, Client } from "../../types";
import { PAYMENT_METHOD_LABEL } from "../../types";
import { Dialog, DialogContent, DialogTitle, DialogDescription } from "../ui/dialog";
import { fmtDate, fmtDateTime, fmtMoney } from "../../lib/format";
import { Button } from "../ui/button";
import { Badge } from "../ui/badge";
import { Input } from "../ui/input";
import { Label } from "../ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../ui/select";
import { RefreshCw, Save, BookCheck, BookX, Download } from "lucide-react";
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
  const { data: clients } = useQuery<Client[]>({
    queryKey: ["clients", data?.organization_id],
    queryFn: () => api("/clients", { query: { organization_id: data?.organization_id } }),
    enabled: !!data,
  });

  useEffect(() => { setEdit({}); }, [id]);

  const patch = useMutation({
    mutationFn: (body: any) => api<ReceiptDetail>(`/receipts/${id}`, { method: "PATCH", body }),
    onSuccess: () => { toast({ title: "Saved", variant: "success" }); qc.invalidateQueries({ queryKey: ["receipts"] }); qc.invalidateQueries({ queryKey: ["receipt", id] }); setEdit({}); },
    onError: (e: any) => toast({ title: "Save failed", description: e.message, variant: "destructive" }),
  });

  const reprocess = useMutation({
    mutationFn: () => api(`/receipts/${id}/reprocess`, { method: "POST" }),
    onSuccess: () => toast({ title: "Reprocessing enqueued" }),
  });

  const book = useMutation({
    mutationFn: () => api(`/receipts/${id}/book`, { method: "POST" }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["receipt", id] }); qc.invalidateQueries({ queryKey: ["receipts"] }); toast({ title: "Marked as booked", variant: "success" }); },
  });
  const unbook = useMutation({
    mutationFn: () => api(`/receipts/${id}/unbook`, { method: "POST" }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["receipt", id] }); qc.invalidateQueries({ queryKey: ["receipts"] }); toast({ title: "Unbooked" }); },
  });

  return (
    <Dialog open={!!id} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-5xl h-[85vh] grid-cols-2 grid grid-rows-[auto_1fr] p-0">
        {data && (
          <>
            <div className="col-span-2 p-4 border-b border-border flex items-center justify-between">
              <div className="min-w-0">
                <DialogTitle className="truncate">{data.filename}</DialogTitle>
                <DialogDescription className="text-xs">
                  Received {fmtDateTime(data.received_at)} · Issued {fmtDate(data.document_date)}{data.due_date ? ` · Due ${fmtDate(data.due_date)}` : ""}
                </DialogDescription>
              </div>
              <div className="flex items-center gap-2">
                {data.booked_at ? (
                  <Button size="sm" variant="outline" onClick={() => unbook.mutate()}><BookX className="h-3.5 w-3.5 mr-1" /> Unbook</Button>
                ) : (
                  <Button size="sm" onClick={() => book.mutate()}><BookCheck className="h-3.5 w-3.5 mr-1" /> Mark booked</Button>
                )}
                <Button size="sm" variant="outline" onClick={() => reprocess.mutate()}><RefreshCw className="h-3.5 w-3.5 mr-1" /> Reprocess</Button>
                <a href={`${apiBase}/receipts/${data.id}/file`} download={data.filename}>
                  <Button size="sm" variant="outline"><Download className="h-3.5 w-3.5 mr-1" /> Download</Button>
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
                <div className="text-xs uppercase tracking-wider text-muted-foreground mb-2">Metadata</div>
                <div className="grid grid-cols-2 gap-3">
                  <Field label="Provider">
                    <Select value={String(edit.provider_id ?? data.provider_id ?? "")} onValueChange={(v) => setEdit((e: any) => ({ ...e, provider_id: parseInt(v) }))}>
                      <SelectTrigger><SelectValue placeholder="—" /></SelectTrigger>
                      <SelectContent>
                        {(providers ?? []).map((p) => <SelectItem key={p.id} value={String(p.id)}>{p.display_name}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </Field>
                  <Field label="Client">
                    <Select value={String(edit.client_id ?? data.client_id ?? "")} onValueChange={(v) => setEdit((e: any) => ({ ...e, client_id: parseInt(v) }))}>
                      <SelectTrigger><SelectValue placeholder="—" /></SelectTrigger>
                      <SelectContent>
                        {(clients ?? []).map((c) => <SelectItem key={c.id} value={String(c.id)}>{c.name}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </Field>
                  <Field label="Amount">
                    <Input value={edit.amount ?? data.amount ?? ""} onChange={(e) => setEdit((s: any) => ({ ...s, amount: e.target.value }))} />
                  </Field>
                  <Field label="Currency">
                    <Input value={edit.currency ?? data.currency ?? ""} onChange={(e) => setEdit((s: any) => ({ ...s, currency: e.target.value.toUpperCase() }))} />
                  </Field>
                  <Field label="Date of issue">
                    <Input
                      type="date"
                      value={(edit.document_date ?? data.document_date ?? "").slice(0, 10)}
                      onChange={(e) => setEdit((s: any) => ({ ...s, document_date: e.target.value }))}
                      title="Rechnungsdatum — when the invoice was issued. Drives accounting periods."
                    />
                  </Field>
                  <Field label="Due date">
                    <Input
                      type="date"
                      value={(edit.due_date ?? data.due_date ?? "").slice(0, 10)}
                      onChange={(e) => setEdit((s: any) => ({ ...s, due_date: e.target.value }))}
                      title="Fälligkeitsdatum — when payment is due. Often empty for already-paid CC charges."
                    />
                  </Field>
                  <Field label="Invoice #">
                    <Input value={edit.invoice_number ?? data.invoice_number ?? ""} onChange={(e) => setEdit((s: any) => ({ ...s, invoice_number: e.target.value }))} />
                  </Field>
                  <Field label="Payment method">
                    <Select value={edit.payment_method ?? data.payment_method} onValueChange={(v) => setEdit((s: any) => ({ ...s, payment_method: v }))}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        {(Object.keys(PAYMENT_METHOD_LABEL) as PaymentMethod[]).map((p) => (
                          <SelectItem key={p} value={p}>{PAYMENT_METHOD_LABEL[p]}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </Field>
                  <Field label="Brand">
                    <Input value={edit.brand ?? data.brand ?? ""} placeholder="leckker / sichersatt / ..." onChange={(e) => setEdit((s: any) => ({ ...s, brand: e.target.value }))} />
                  </Field>
                  <Field label="VAT rate %">
                    <Input type="number" step="0.1" value={edit.vat_rate ?? data.vat_rate ?? ""} placeholder="e.g. 8.1" onChange={(e) => setEdit((s: any) => ({ ...s, vat_rate: e.target.value }))} />
                  </Field>
                  <Field label="VAT amount">
                    <Input type="number" step="0.01" value={edit.vat_amount ?? data.vat_amount ?? ""} placeholder="auto / manual" onChange={(e) => setEdit((s: any) => ({ ...s, vat_amount: e.target.value }))} />
                  </Field>
                  <Field label="Bookkeeping ref">
                    <Input value={edit.bookkeeping_ref ?? data.bookkeeping_ref ?? ""} placeholder="Bexio #, journal entry…" onChange={(e) => setEdit((s: any) => ({ ...s, bookkeeping_ref: e.target.value }))} />
                  </Field>
                  <Field label="Status">
                    <Select value={edit.status ?? data.status} onValueChange={(v) => setEdit((s: any) => ({ ...s, status: v }))}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="processed">processed</SelectItem>
                        <SelectItem value="review_needed">review_needed</SelectItem>
                        <SelectItem value="archived">archived</SelectItem>
                      </SelectContent>
                    </Select>
                  </Field>
                  <Field label="Confidence">
                    <div className="text-sm h-9 flex items-center px-1">{Math.round(parseFloat(data.confidence) * 100)}%</div>
                  </Field>
                </div>
                <div className="mt-3">
                  <Label className="text-xs">Notes</Label>
                  <Textarea
                    rows={2}
                    placeholder="Why is this expense — context for the accountant…"
                    value={edit.notes ?? data.notes ?? ""}
                    onChange={(e) => setEdit((s: any) => ({ ...s, notes: e.target.value }))}
                    className="mt-1"
                  />
                </div>
                <Button className="mt-3" size="sm" disabled={!Object.keys(edit).length} onClick={() => patch.mutate(edit)}>
                  <Save className="h-3.5 w-3.5 mr-1" /> Save
                </Button>
                {data.booked_at && (
                  <p className="text-[11px] text-muted-foreground mt-2">
                    Booked {fmtDateTime(data.booked_at)}{data.bookkeeping_ref ? ` · ref ${data.bookkeeping_ref}` : ""}
                  </p>
                )}
              </section>

              <section>
                <div className="text-xs uppercase tracking-wider text-muted-foreground mb-2">Sync targets</div>
                <div className="space-y-1.5">
                  {(data.sync_targets ?? []).map((t) => (
                    <div key={t.id} className="flex items-center justify-between text-sm">
                      <div>Connector #{t.connector_id}</div>
                      <Badge variant={t.status === "synced" ? "success" : t.status === "failed" ? "destructive" : "secondary"}>
                        {t.status}
                      </Badge>
                    </div>
                  ))}
                  {!(data.sync_targets ?? []).length && <p className="text-sm text-muted-foreground">No sync targets configured.</p>}
                </div>
              </section>

              <section>
                <div className="text-xs uppercase tracking-wider text-muted-foreground mb-2">Processing history</div>
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
        {isLoading && <div className="p-6 col-span-2">Loading…</div>}
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
