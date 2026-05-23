import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../../lib/api";
import type { Connector, ConnectorType, Organization } from "../../types";
import { Card } from "../../components/ui/card";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "../../components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { Plus, Trash2, TestTube, Plug } from "lucide-react";
import { useUi } from "../../store/ui";
import { toast } from "../../components/ui/toaster";
import { Badge } from "../../components/ui/badge";

export default function Connectors() {
  const orgId = useUi((s) => s.selectedOrgId);
  const qc = useQueryClient();
  const { data: connectors } = useQuery<Connector[]>({
    queryKey: ["connectors", orgId], queryFn: () => api("/connectors", { query: { organization_id: orgId ?? undefined } }),
  });
  const { data: orgs } = useQuery<Organization[]>({ queryKey: ["orgs"], queryFn: () => api("/organizations") });

  const [adding, setAdding] = useState<ConnectorType | null>(null);
  const del = useMutation({
    mutationFn: (id: number) => api(`/connectors/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["connectors"] }),
  });
  const test = useMutation({
    mutationFn: (id: number) => api<{ ok: boolean; error?: string }>(`/connectors/${id}/test`, { method: "POST" }),
    onSuccess: (r) => toast({ title: r.ok ? "Verbindung OK" : "Verbindung fehlgeschlagen", description: r.error, variant: r.ok ? "success" : "destructive" }),
  });

  return (
    <div className="p-4 sm:p-6 space-y-4">
      <header className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">Connectoren</h1>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => setAdding("local")}><Plus className="h-4 w-4 mr-1" /> Lokal</Button>
          <Button variant="outline" onClick={() => setAdding("onedrive")}><Plus className="h-4 w-4 mr-1" /> OneDrive</Button>
          <Button variant="outline" onClick={() => setAdding("bexio")}><Plus className="h-4 w-4 mr-1" /> Bexio</Button>
        </div>
      </header>
      <Card>
        <div className="divide-y divide-border">
          {(connectors ?? []).map((c) => (
            <div key={c.id} className="p-4 flex items-center gap-3">
              <Plug className="h-4 w-4 text-muted-foreground" />
              <div className="flex-1">
                <div className="font-medium">{c.name}</div>
                <div className="text-xs text-muted-foreground"><Badge variant="outline">{c.type}</Badge> · Firma #{c.organization_id} · {c.enabled ? "aktiv" : "inaktiv"}</div>
              </div>
              <Button size="sm" variant="outline" onClick={() => test.mutate(c.id)}><TestTube className="h-3.5 w-3.5 mr-1" /> Testen</Button>
              <Button size="icon" variant="ghost" onClick={() => confirm("Connector wirklich löschen?") && del.mutate(c.id)}><Trash2 className="h-4 w-4" /></Button>
            </div>
          ))}
          {!connectors?.length && <div className="p-6 text-center text-muted-foreground">Noch keine Connectoren.</div>}
        </div>
      </Card>

      {adding && (
        <ConnectorDialog
          type={adding}
          orgs={orgs ?? []}
          defaultOrgId={orgId}
          onClose={() => setAdding(null)}
          onSaved={() => { qc.invalidateQueries({ queryKey: ["connectors"] }); setAdding(null); }}
        />
      )}
    </div>
  );
}

function ConnectorDialog({ type, orgs, defaultOrgId, onClose, onSaved }: {
  type: ConnectorType; orgs: Organization[]; defaultOrgId: number | null; onClose: () => void; onSaved: () => void;
}) {
  const [organization_id, setOrg] = useState<number | undefined>(defaultOrgId ?? orgs[0]?.id);
  const [name, setName] = useState(`${type[0].toUpperCase() + type.slice(1)} Ziel`);
  const [config, setConfig] = useState<Record<string, any>>(
    type === "local" ? { base_path: "/data/local-mirror", subpath_template: "{org}/{year}/{month}" } :
    type === "onedrive" ? { folder_path: "/Belege" } :
    type === "bexio" ? { api_token: "" } : {}
  );

  const save = useMutation({
    mutationFn: () => api("/connectors", { method: "POST", body: { organization_id, type, name, enabled: true, config } }),
    onSuccess: () => onSaved(),
    onError: (e: any) => toast({ title: "Fehlgeschlagen", description: e.message, variant: "destructive" }),
  });
  const startOneDrive = useMutation({
    mutationFn: () => api<{ authorize_url: string }>(`/connectors/onedrive/authorize`, { query: { organization_id, name } }),
    onSuccess: (r) => { window.location.href = r.authorize_url; },
  });

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader><DialogTitle>{type === "local" ? "Lokalen" : type === "onedrive" ? "OneDrive-" : "Bexio-"} Connector hinzufügen</DialogTitle></DialogHeader>
        <div className="space-y-3">
          <div>
            <Label>Firma</Label>
            <Select value={organization_id ? String(organization_id) : undefined} onValueChange={(v) => setOrg(parseInt(v))}>
              <SelectTrigger><SelectValue placeholder="Auswählen…" /></SelectTrigger>
              <SelectContent>{orgs.map((o) => <SelectItem key={o.id} value={String(o.id)}>{o.name}</SelectItem>)}</SelectContent>
            </Select>
          </div>
          <div><Label>Name</Label><Input value={name} onChange={(e) => setName(e.target.value)} /></div>
          {type === "local" && (
            <>
              <div><Label>Basis-Pfad</Label><Input value={config.base_path} onChange={(e) => setConfig((c) => ({ ...c, base_path: e.target.value }))} /></div>
              <div><Label>Unterpfad-Vorlage</Label><Input value={config.subpath_template} onChange={(e) => setConfig((c) => ({ ...c, subpath_template: e.target.value }))} /></div>
            </>
          )}
          {type === "onedrive" && (
            <>
              <div><Label>Ordnerpfad</Label><Input value={config.folder_path} onChange={(e) => setConfig((c) => ({ ...c, folder_path: e.target.value }))} /></div>
              <p className="text-xs text-muted-foreground">OneDrive nutzt OAuth. Sie werden zu Microsoft weitergeleitet, um diesen Connector zu autorisieren.</p>
              <Button onClick={() => startOneDrive.mutate()} className="w-full">Mit Microsoft autorisieren</Button>
            </>
          )}
          {type === "bexio" && (
            <>
              <div><Label>Bexio-API-Token</Label><Input type="password" value={config.api_token} onChange={(e) => setConfig((c) => ({ ...c, api_token: e.target.value }))} /></div>
              <p className="text-xs text-muted-foreground">Der Token wird verschlüsselt gespeichert.</p>
            </>
          )}
          {type !== "onedrive" && (
            <div className="flex justify-end gap-2 pt-2">
              <Button variant="outline" onClick={onClose}>Abbrechen</Button>
              <Button onClick={() => save.mutate()}>Speichern</Button>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
