import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../../lib/api";
import type {
  Organization,
  Provider,
  ProviderAccountMapping,
  ProviderRule,
  MatchType,
} from "../../types";
import { Card } from "../../components/ui/card";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "../../components/ui/dialog";
import { Plus, Edit3, Trash2, Calculator } from "lucide-react";
import { toast } from "../../components/ui/toaster";
import { Badge } from "../../components/ui/badge";

const MATCH_TYPES: MatchType[] = ["sender_domain", "sender_email", "subject_contains", "body_contains", "sender_contains"];

export default function Providers() {
  const qc = useQueryClient();
  const { data: providers } = useQuery<Provider[]>({ queryKey: ["providers"], queryFn: () => api("/providers") });
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<Provider | null>(null);
  const [openRulesFor, setOpenRulesFor] = useState<Provider | null>(null);
  const [openMappingFor, setOpenMappingFor] = useState<Provider | null>(null);

  const save = useMutation({
    mutationFn: async (body: any) => {
      if (editing) return api(`/providers/${editing.id}`, { method: "PATCH", body });
      return api("/providers", { method: "POST", body });
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["providers"] }); setCreating(false); setEditing(null); toast({ title: "Gespeichert", variant: "success" }); },
  });
  const del = useMutation({
    mutationFn: (id: number) => api(`/providers/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["providers"] }),
  });

  return (
    <div className="p-4 sm:p-6 space-y-4">
      <header className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">Anbieter & Regeln</h1>
        <Button onClick={() => setCreating(true)}><Plus className="h-4 w-4 mr-1" /> Anbieter hinzufügen</Button>
      </header>
      <Card>
        <div className="divide-y divide-border">
          {(providers ?? []).map((p) => (
            <div key={p.id} className="p-4 flex items-center gap-3">
              <div className="flex-1">
                <div className="font-medium">{p.display_name}</div>
                <div className="text-xs text-muted-foreground">Slug: {p.slug} {p.category && <Badge variant="outline" className="ml-2">{p.category}</Badge>}</div>
              </div>
              <Button size="sm" variant="outline" onClick={() => setOpenRulesFor(p)}>Regeln bearbeiten</Button>
              <Button size="sm" variant="outline" onClick={() => setOpenMappingFor(p)}>
                <Calculator className="h-3.5 w-3.5 mr-1" /> Konto-Mapping
              </Button>
              <Button size="icon" variant="ghost" onClick={() => setEditing(p)}><Edit3 className="h-4 w-4" /></Button>
              <Button size="icon" variant="ghost" onClick={() => confirm("Anbieter wirklich löschen?") && del.mutate(p.id)}><Trash2 className="h-4 w-4" /></Button>
            </div>
          ))}
        </div>
      </Card>

      <ProviderDialog
        open={creating || !!editing}
        prov={editing}
        onClose={() => { setCreating(false); setEditing(null); }}
        onSave={(b) => save.mutate(b)}
      />
      {openRulesFor && (
        <RulesDialog
          provider={openRulesFor}
          onClose={() => setOpenRulesFor(null)}
        />
      )}
      {openMappingFor && (
        <AccountMappingDialog
          provider={openMappingFor}
          onClose={() => setOpenMappingFor(null)}
        />
      )}
    </div>
  );
}

function ProviderDialog({ open, prov, onClose, onSave }: { open: boolean; prov: Provider | null; onClose: () => void; onSave: (body: any) => void }) {
  const [slug, setSlug] = useState(prov?.slug ?? "");
  const [display_name, setDisplay] = useState(prov?.display_name ?? "");
  const [category, setCategory] = useState(prov?.category ?? "");
  const [default_currency, setDc] = useState(prov?.default_currency ?? "CHF");

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader><DialogTitle>{prov ? "Anbieter bearbeiten" : "Neuer Anbieter"}</DialogTitle></DialogHeader>
        <div className="space-y-3">
          <div><Label>Slug</Label><Input value={slug} onChange={(e) => setSlug(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, "-"))} /></div>
          <div><Label>Anzeigename</Label><Input value={display_name} onChange={(e) => setDisplay(e.target.value)} /></div>
          <div className="grid grid-cols-2 gap-2">
            <div><Label>Kategorie</Label><Input value={category} onChange={(e) => setCategory(e.target.value)} /></div>
            <div><Label>Standardwährung</Label><Input value={default_currency} onChange={(e) => setDc(e.target.value.toUpperCase())} /></div>
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={onClose}>Abbrechen</Button>
            <Button onClick={() => onSave({ slug, display_name, category, default_currency })}>Speichern</Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function AccountMappingDialog({
  provider,
  onClose,
}: {
  provider: Provider;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const { data: orgs } = useQuery<Organization[]>({
    queryKey: ["orgs"],
    queryFn: () => api("/organizations"),
  });
  const { data: mappings } = useQuery<ProviderAccountMapping[]>({
    queryKey: ["account-mappings", provider.id],
    queryFn: () =>
      api("/providers/account-mappings", {
        query: { provider_id: provider.id },
      }),
  });

  const upsert = useMutation({
    mutationFn: (body: {
      provider_id: number;
      organization_id: number;
      account_code: string;
      vat_code: string | null;
    }) =>
      api("/providers/account-mappings", { method: "POST", body }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["account-mappings", provider.id] });
      toast({ title: "Mapping gespeichert", variant: "success" });
    },
    onError: (e: any) =>
      toast({
        title: "Fehlgeschlagen",
        description: e.message,
        variant: "destructive",
      }),
  });

  const remove = useMutation({
    mutationFn: (id: number) =>
      api(`/providers/account-mappings/${id}`, { method: "DELETE" }),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["account-mappings", provider.id] }),
  });

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>
            Konto-Mapping · {provider.display_name}
          </DialogTitle>
        </DialogHeader>
        <p className="text-xs text-muted-foreground">
          Pro Firma kann hier festgelegt werden, auf welches Konto (und
          optional welchen USt-Code) Belege dieses Anbieters in Bexio gebucht
          werden. Leer = Standard aus den Connector-Einstellungen verwenden.
        </p>
        <div className="rounded-md border border-border divide-y divide-border">
          {(orgs ?? []).map((o) => {
            const existing = (mappings ?? []).find(
              (m) => m.organization_id === o.id,
            );
            return (
              <MappingRow
                key={o.id}
                org={o}
                existing={existing}
                onSave={(account_code, vat_code) =>
                  upsert.mutate({
                    provider_id: provider.id,
                    organization_id: o.id,
                    account_code,
                    vat_code,
                  })
                }
                onDelete={existing ? () => remove.mutate(existing.id) : undefined}
              />
            );
          })}
          {!orgs?.length && (
            <div className="p-4 text-center text-muted-foreground text-sm">
              Keine Firmen vorhanden.
            </div>
          )}
        </div>
        <div className="flex justify-end pt-2">
          <Button variant="outline" onClick={onClose}>
            Schließen
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function MappingRow({
  org,
  existing,
  onSave,
  onDelete,
}: {
  org: Organization;
  existing: ProviderAccountMapping | undefined;
  onSave: (account_code: string, vat_code: string | null) => void;
  onDelete?: () => void;
}) {
  const [account, setAccount] = useState(existing?.account_code ?? "");
  const [vat, setVat] = useState(existing?.vat_code ?? "");
  const dirty =
    account !== (existing?.account_code ?? "") ||
    vat !== (existing?.vat_code ?? "");
  return (
    <div className="p-3 grid grid-cols-12 items-end gap-2">
      <div className="col-span-4">
        <div className="text-sm font-medium">{org.name}</div>
        <div className="text-xs text-muted-foreground">
          Std.-Währung {org.default_currency}
        </div>
      </div>
      <div className="col-span-3">
        <Label className="text-xs">Konto</Label>
        <Input
          value={account}
          onChange={(e) => setAccount(e.target.value)}
          placeholder="6510"
        />
      </div>
      <div className="col-span-3">
        <Label className="text-xs">USt-Code</Label>
        <Input
          value={vat}
          onChange={(e) => setVat(e.target.value)}
          placeholder="VST077"
        />
      </div>
      <div className="col-span-2 flex justify-end gap-1">
        {onDelete && (
          <Button
            size="icon"
            variant="ghost"
            title="Mapping entfernen"
            onClick={onDelete}
          >
            <Trash2 className="h-4 w-4" />
          </Button>
        )}
        <Button
          size="sm"
          disabled={!account.trim() || !dirty}
          onClick={() => onSave(account.trim(), vat.trim() || null)}
        >
          Speichern
        </Button>
      </div>
    </div>
  );
}


function RulesDialog({ provider, onClose }: { provider: Provider; onClose: () => void }) {
  const qc = useQueryClient();
  const { data: rules } = useQuery<ProviderRule[]>({
    queryKey: ["provider-rules", provider.id],
    queryFn: () => api("/providers/rules", { query: { provider_id: provider.id } }),
  });
  const [matchType, setMatchType] = useState<MatchType>("sender_domain");
  const [matchValue, setMatchValue] = useState("");
  const add = useMutation({
    mutationFn: () => api("/providers/rules", { method: "POST", body: { provider_id: provider.id, organization_id: null, match_type: matchType, match_value: matchValue, priority: 110 } }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["provider-rules", provider.id] }); setMatchValue(""); toast({ title: "Regel hinzugefügt" }); },
  });
  const del = useMutation({
    mutationFn: (id: number) => api(`/providers/rules/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["provider-rules", provider.id] }),
  });
  const matchLabel: Record<MatchType, string> = {
    sender_domain: "Absender-Domain",
    sender_email: "Absender-E-Mail",
    subject_contains: "Betreff enthält",
    body_contains: "Inhalt enthält",
    plus_alias: "Plus-Alias",
    sender_contains: "Absender enthält",
  };
  return (
    <Dialog open={true} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader><DialogTitle>Regeln · {provider.display_name}</DialogTitle></DialogHeader>
        <div className="space-y-3">
          <div className="flex items-end gap-2">
            <div className="w-48">
              <Label>Match-Typ</Label>
              <Select value={matchType} onValueChange={(v) => setMatchType(v as MatchType)}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>{MATCH_TYPES.map((m) => <SelectItem key={m} value={m}>{matchLabel[m]}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <div className="flex-1"><Label>Wert</Label><Input value={matchValue} onChange={(e) => setMatchValue(e.target.value)} placeholder="example.com oder ein Stichwort" /></div>
            <Button onClick={() => add.mutate()} disabled={!matchValue}>Hinzufügen</Button>
          </div>
          <div className="divide-y divide-border border border-border rounded-md max-h-72 overflow-auto">
            {(rules ?? []).map((r) => (
              <div key={r.id} className="p-2.5 flex items-center justify-between text-sm">
                <div>
                  <Badge variant="outline" className="mr-2">{matchLabel[r.match_type] ?? r.match_type}</Badge>
                  <span className="font-mono">{r.match_value}</span>
                </div>
                <Button size="icon" variant="ghost" onClick={() => del.mutate(r.id)}><Trash2 className="h-4 w-4" /></Button>
              </div>
            ))}
            {!rules?.length && <div className="p-4 text-center text-muted-foreground">Noch keine Regeln.</div>}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
