import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../../lib/api";
import type { Client, ClientMapping, Organization, Provider, MatchType } from "../../types";
import { Card } from "../../components/ui/card";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "../../components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { Plus, Trash2 } from "lucide-react";
import { useUi } from "../../store/ui";
import { Badge } from "../../components/ui/badge";

const MATCH_TYPES: MatchType[] = ["plus_alias", "sender_contains", "subject_contains", "body_contains"];

export default function Clients() {
  const qc = useQueryClient();
  const orgId = useUi((s) => s.selectedOrgId);
  const { data: orgs } = useQuery<Organization[]>({ queryKey: ["orgs"], queryFn: () => api("/organizations") });
  const { data: clients } = useQuery<Client[]>({
    queryKey: ["clients", orgId], queryFn: () => api("/clients", { query: { organization_id: orgId ?? undefined } }), enabled: !!orgId,
  });
  const { data: providers } = useQuery<Provider[]>({ queryKey: ["providers"], queryFn: () => api("/providers") });
  const [creating, setCreating] = useState(false);
  const [mappingFor, setMappingFor] = useState<Client | null>(null);

  const save = useMutation({
    mutationFn: (body: any) => api("/clients", { method: "POST", body }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["clients"] }); setCreating(false); },
  });
  const del = useMutation({
    mutationFn: (id: number) => api(`/clients/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["clients"] }),
  });

  return (
    <div className="p-4 sm:p-6 space-y-4">
      <header className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">Sub-clients</h1>
        <Button onClick={() => setCreating(true)} disabled={!orgId}><Plus className="h-4 w-4 mr-1" /> Add sub-client</Button>
      </header>
      <p className="text-sm text-muted-foreground">
        Sub-clients let you split receipts that arrive under one shared mailbox across different brands or business units (e.g. <em>leckker</em> vs <em>sichersatt</em>).
      </p>

      <Card>
        <div className="divide-y divide-border">
          {(clients ?? []).map((c) => (
            <div key={c.id} className="p-4 flex items-center gap-3">
              <div className="flex-1">
                <div className="font-medium">{c.name}</div>
                <div className="text-xs text-muted-foreground">slug: {c.slug}</div>
              </div>
              <Button size="sm" variant="outline" onClick={() => setMappingFor(c)}>Mappings</Button>
              <Button size="icon" variant="ghost" onClick={() => confirm("Delete?") && del.mutate(c.id)}><Trash2 className="h-4 w-4" /></Button>
            </div>
          ))}
          {!clients?.length && <div className="p-6 text-center text-muted-foreground">No sub-clients for this organization.</div>}
        </div>
      </Card>

      {creating && <CreateDialog orgId={orgId!} onClose={() => setCreating(false)} onSave={(b) => save.mutate(b)} />}
      {mappingFor && <MappingsDialog client={mappingFor} providers={providers ?? []} onClose={() => setMappingFor(null)} />}
    </div>
  );
}

function CreateDialog({ orgId, onClose, onSave }: { orgId: number; onClose: () => void; onSave: (b: any) => void }) {
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  return (
    <Dialog open={true} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader><DialogTitle>New sub-client</DialogTitle></DialogHeader>
        <div className="space-y-2">
          <div><Label>Name</Label><Input value={name} onChange={(e) => { setName(e.target.value); if (!slug) setSlug(e.target.value.toLowerCase().replace(/[^a-z0-9]/g, "")); }} /></div>
          <div><Label>Slug</Label><Input value={slug} onChange={(e) => setSlug(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, "-"))} /></div>
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={onClose}>Cancel</Button>
            <Button onClick={() => onSave({ organization_id: orgId, name, slug })}>Save</Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function MappingsDialog({ client, providers, onClose }: { client: Client; providers: Provider[]; onClose: () => void }) {
  const qc = useQueryClient();
  const { data: mappings } = useQuery<ClientMapping[]>({
    queryKey: ["client-mappings", client.id],
    queryFn: () => api("/clients/mappings", { query: { client_id: client.id } }),
  });
  const [mt, setMt] = useState<MatchType>("plus_alias");
  const [mv, setMv] = useState("");
  const [providerId, setProviderId] = useState<number | null>(null);

  const add = useMutation({
    mutationFn: () => api("/clients/mappings", { method: "POST", body: { client_id: client.id, provider_id: providerId, match_type: mt, match_value: mv } }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["client-mappings", client.id] }); setMv(""); },
  });
  const del = useMutation({
    mutationFn: (id: number) => api(`/clients/mappings/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["client-mappings", client.id] }),
  });

  return (
    <Dialog open={true} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader><DialogTitle>Mappings · {client.name}</DialogTitle></DialogHeader>
        <div className="space-y-3">
          <div className="grid grid-cols-12 items-end gap-2">
            <div className="col-span-4"><Label>Match type</Label>
              <Select value={mt} onValueChange={(v) => setMt(v as MatchType)}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>{MATCH_TYPES.map((m) => <SelectItem key={m} value={m}>{m}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <div className="col-span-5"><Label>Value</Label><Input value={mv} onChange={(e) => setMv(e.target.value)} placeholder="leckker  /  +leckker@trafficflow.ch" /></div>
            <div className="col-span-3"><Label>Provider (opt)</Label>
              <Select value={providerId ? String(providerId) : undefined} onValueChange={(v) => setProviderId(parseInt(v))}>
                <SelectTrigger><SelectValue placeholder="Any" /></SelectTrigger>
                <SelectContent>{providers.map((p) => <SelectItem key={p.id} value={String(p.id)}>{p.display_name}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <Button className="col-span-12" disabled={!mv} onClick={() => add.mutate()}>Add mapping</Button>
          </div>
          <div className="divide-y divide-border border border-border rounded-md max-h-72 overflow-auto">
            {(mappings ?? []).map((m) => (
              <div key={m.id} className="p-2.5 flex items-center justify-between text-sm">
                <div className="space-x-2">
                  <Badge variant="outline">{m.match_type}</Badge>
                  <span className="font-mono">{m.match_value}</span>
                  {m.provider_id && <Badge variant="secondary">prov #{m.provider_id}</Badge>}
                </div>
                <Button size="icon" variant="ghost" onClick={() => del.mutate(m.id)}><Trash2 className="h-4 w-4" /></Button>
              </div>
            ))}
            {!mappings?.length && <div className="p-4 text-center text-muted-foreground text-sm">No mappings yet.</div>}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
