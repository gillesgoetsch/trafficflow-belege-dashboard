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
import { RefreshCw, Save } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "../ui/toaster";

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

  return (
    <Dialog open={!!id} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-5xl h-[85vh] grid-cols-2 grid grid-rows-[auto_1fr] p-0">
        {data && (
          <>
            <div className="col-span-2 p-4 border-b border-border flex items-center justify-between">
              <div className="min-w-0">
                <DialogTitle className="truncate">{data.filename}</DialogTitle>
                <DialogDescription className="text-xs">
                  Received {fmtDateTime(data.received_at)} · Document date {fmtDate(data.document_date)}
                </DialogDescription>
              </div>
              <div className="flex items-center gap-2">
                <Button size="sm" variant="outline" onClick={() => reprocess.mutate()}><RefreshCw className="h-3.5 w-3.5 mr-1" /> Reprocess</Button>
                <a href={`${apiBase}/receipts/${data.id}/file`} target="_blank" rel="noreferrer">
                  <Button size="sm" variant="outline">Open file</Button>
                </a>
              </div>
            </div>

            <div className="overflow-auto bg-muted/30 border-r border-border relative">
              {/\.pdf$/i.test(data.filename) ? (
                <object
                  data={`${apiBase}/receipts/${data.id}/file#toolbar=0&navpanes=0`}
                  type="application/pdf"
                  className="w-full h-full min-h-[60vh]"
                >
                  <div className="p-6 text-sm text-muted-foreground space-y-2 text-center">
                    <p>Your browser can't preview this PDF inline.</p>
                    <a className="inline-block text-primary underline"
                       href={`${apiBase}/receipts/${data.id}/file`}
                       target="_blank" rel="noreferrer">
                      Open the PDF in a new tab
                    </a>
                  </div>
                </object>
              ) : (
                <img
                  src={`${apiBase}/receipts/${data.id}/file`}
                  alt={data.filename}
                  className="w-full h-auto max-h-[80vh] mx-auto object-contain"
                />
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
                  <Field label="Document date">
                    <Input type="date" value={(edit.document_date ?? data.document_date ?? "").slice(0, 10)} onChange={(e) => setEdit((s: any) => ({ ...s, document_date: e.target.value }))} />
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
                <Button className="mt-3" size="sm" disabled={!Object.keys(edit).length} onClick={() => patch.mutate(edit)}>
                  <Save className="h-3.5 w-3.5 mr-1" /> Save
                </Button>
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
