import { useDropzone } from "react-dropzone";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../lib/api";
import { useUi } from "../store/ui";
import type { Organization, PaymentMethod, Provider, Client } from "../types";
import { PAYMENT_METHOD_LABEL } from "../types";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select";
import { Button } from "../components/ui/button";
import { toast } from "../components/ui/toaster";
import { UploadCloud, FileText, CheckCircle2, XCircle } from "lucide-react";
import { cn } from "../lib/utils";

type UploadEntry = { file: File; status: "queued" | "uploading" | "done" | "error"; error?: string; id?: number };

export default function Upload() {
  const orgId = useUi((s) => s.selectedOrgId);
  const [providerId, setProviderId] = useState<number | null>(null);
  const [clientId, setClientId] = useState<number | null>(null);
  const [paymentMethod, setPaymentMethod] = useState<PaymentMethod>("unknown");
  const [brand, setBrand] = useState<string>("");
  const [entries, setEntries] = useState<UploadEntry[]>([]);
  const qc = useQueryClient();

  const { data: orgs } = useQuery<Organization[]>({ queryKey: ["orgs"], queryFn: () => api("/organizations") });
  const { data: providers } = useQuery<Provider[]>({ queryKey: ["providers"], queryFn: () => api("/providers") });
  const { data: clients } = useQuery<Client[]>({
    queryKey: ["clients", orgId],
    queryFn: () => api("/clients", { query: { organization_id: orgId } }),
    enabled: !!orgId,
  });

  const upload = useMutation({
    mutationFn: async (e: UploadEntry) => {
      if (!orgId) throw new Error("Select an organization first");
      const form = new FormData();
      form.append("organization_id", String(orgId));
      if (providerId) form.append("provider_id", String(providerId));
      if (clientId) form.append("client_id", String(clientId));
      if (paymentMethod) form.append("payment_method", paymentMethod);
      if (brand) form.append("brand", brand);
      form.append("file", e.file);
      return await api("/upload", { method: "POST", body: form });
    },
  });

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    accept: { "application/pdf": [], "image/*": [] },
    onDrop: async (files) => {
      if (!orgId) { toast({ title: "Select an organization first", variant: "destructive" }); return; }
      const next = files.map((file) => ({ file, status: "queued" as const }));
      setEntries((s) => [...next, ...s]);
      for (const e of next) {
        setEntries((s) => s.map((x) => x.file === e.file ? { ...x, status: "uploading" } : x));
        try {
          const res: any = await upload.mutateAsync(e);
          setEntries((s) => s.map((x) => x.file === e.file ? { ...x, status: "done", id: res.receipt_id } : x));
        } catch (err: any) {
          setEntries((s) => s.map((x) => x.file === e.file ? { ...x, status: "error", error: err.message } : x));
        }
      }
      qc.invalidateQueries({ queryKey: ["receipts"] });
    },
  });

  const currentOrg = orgs?.find((o) => o.id === orgId);

  return (
    <div className="p-4 sm:p-6 max-w-3xl mx-auto space-y-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Upload receipts</h1>
        <p className="text-sm text-muted-foreground">Drag & drop PDFs or photos. Metadata is extracted automatically.</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Pre-fill</CardTitle>
          <CardDescription>Optional — only used if metadata extraction can't infer them.</CardDescription>
        </CardHeader>
        <CardContent className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          <div>
            <div className="text-xs text-muted-foreground mb-1">Organization</div>
            <Select value={orgId ? String(orgId) : undefined} onValueChange={(v) => useUi.getState().setSelectedOrgId(parseInt(v))}>
              <SelectTrigger><SelectValue placeholder="Choose…" /></SelectTrigger>
              <SelectContent>{(orgs ?? []).map((o) => <SelectItem key={o.id} value={String(o.id)}>{o.name}</SelectItem>)}</SelectContent>
            </Select>
            {currentOrg && <div className="text-[11px] text-muted-foreground mt-1">Default currency: {currentOrg.default_currency}</div>}
          </div>
          <div>
            <div className="text-xs text-muted-foreground mb-1">Provider (optional)</div>
            <Select value={providerId ? String(providerId) : undefined} onValueChange={(v) => setProviderId(parseInt(v))}>
              <SelectTrigger><SelectValue placeholder="Auto" /></SelectTrigger>
              <SelectContent>{(providers ?? []).map((p) => <SelectItem key={p.id} value={String(p.id)}>{p.display_name}</SelectItem>)}</SelectContent>
            </Select>
          </div>
          <div>
            <div className="text-xs text-muted-foreground mb-1">Payment method</div>
            <Select value={paymentMethod} onValueChange={(v) => setPaymentMethod(v as PaymentMethod)}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {(Object.keys(PAYMENT_METHOD_LABEL) as PaymentMethod[]).map((p) => (
                  <SelectItem key={p} value={p}>{PAYMENT_METHOD_LABEL[p]}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <div className="text-xs text-muted-foreground mb-1">Brand (optional)</div>
            <input
              className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              value={brand}
              placeholder="leckker / sichersatt …"
              onChange={(e) => setBrand(e.target.value)}
            />
          </div>
          {clients?.length ? (
            <div>
              <div className="text-xs text-muted-foreground mb-1">Sub-client (optional)</div>
              <Select value={clientId ? String(clientId) : undefined} onValueChange={(v) => setClientId(parseInt(v))}>
                <SelectTrigger><SelectValue placeholder="None" /></SelectTrigger>
                <SelectContent>{(clients ?? []).map((c) => <SelectItem key={c.id} value={String(c.id)}>{c.name}</SelectItem>)}</SelectContent>
              </Select>
            </div>
          ) : null}
        </CardContent>
      </Card>

      <div
        {...getRootProps({
          className: cn(
            "border-2 border-dashed rounded-xl p-10 text-center cursor-pointer transition-colors",
            isDragActive ? "border-primary bg-primary/5" : "border-border hover:border-primary/60"
          ),
        })}
      >
        <input {...getInputProps()} />
        <UploadCloud className="h-10 w-10 mx-auto text-muted-foreground mb-3" />
        <p className="text-sm">Drop PDFs/images here or click to browse</p>
        <p className="text-xs text-muted-foreground mt-1">Up to 25 MB per file</p>
      </div>

      {entries.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Recent uploads</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {entries.map((e, i) => (
              <div key={i} className="flex items-center gap-3 text-sm">
                <FileText className="h-4 w-4 text-muted-foreground" />
                <span className="flex-1 truncate">{e.file.name}</span>
                {e.status === "uploading" && <span className="text-muted-foreground">Uploading…</span>}
                {e.status === "done" && <span className="flex items-center text-emerald-400"><CheckCircle2 className="h-4 w-4 mr-1" /> Done</span>}
                {e.status === "error" && <span className="flex items-center text-destructive"><XCircle className="h-4 w-4 mr-1" /> {e.error}</span>}
              </div>
            ))}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
