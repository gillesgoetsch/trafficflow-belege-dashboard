import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2, TestTube, RefreshCw, FolderSync, Check, X } from "lucide-react";

import { api } from "../../lib/api";
import { useUi } from "../../store/ui";
import type {
  InboundFile,
  InboundFolder,
  InboundFolderType,
  Organization,
} from "../../types";
import { INBOUND_TYPE_LABEL } from "../../types";
import { fmtRelative, fmtDateTime } from "../../lib/format";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Card } from "../../components/ui/card";
import { Badge } from "../../components/ui/badge";
import { Switch } from "../../components/ui/switch";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "../../components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../../components/ui/select";
import { toast } from "../../components/ui/toaster";

const STATUS_BADGE: Record<InboundFile["status"], { label: string; variant: "default" | "success" | "destructive" | "secondary" | "outline" }> = {
  pending: { label: "wartet", variant: "outline" },
  processing: { label: "läuft", variant: "secondary" },
  processed: { label: "erledigt", variant: "success" },
  failed: { label: "Fehler", variant: "destructive" },
  not_a_receipt: { label: "kein Beleg", variant: "outline" },
};

export default function CloudInbox() {
  const orgId = useUi((s) => s.selectedOrgId);
  const qc = useQueryClient();
  const [adding, setAdding] = useState(false);
  const [selectedFolder, setSelectedFolder] = useState<InboundFolder | null>(null);

  const { data: folders } = useQuery<InboundFolder[]>({
    queryKey: ["inbound-folders", orgId],
    queryFn: () => api("/inbound-folders", { query: { organization_id: orgId ?? undefined } }),
  });
  const { data: orgs } = useQuery<Organization[]>({
    queryKey: ["orgs"],
    queryFn: () => api("/organizations"),
  });

  const del = useMutation({
    mutationFn: (id: number) => api(`/inbound-folders/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["inbound-folders"] }),
  });
  const test = useMutation({
    mutationFn: (id: number) => api<{ ok: boolean; error?: string }>(`/inbound-folders/${id}/test`, { method: "POST" }),
    onSuccess: (r) => toast({
      title: r.ok ? "Verbindung OK" : "Verbindung fehlgeschlagen",
      description: r.error,
      variant: r.ok ? "success" : "destructive",
    }),
  });
  const scan = useMutation({
    mutationFn: (id: number) => api(`/inbound-folders/${id}/scan`, { method: "POST" }),
    onSuccess: () => {
      toast({ title: "Scan gestartet", variant: "success" });
      qc.invalidateQueries({ queryKey: ["inbound-folders"] });
    },
  });
  const toggle = useMutation({
    mutationFn: (vars: { id: number; enabled: boolean }) =>
      api(`/inbound-folders/${vars.id}`, { method: "PATCH", body: { enabled: vars.enabled } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["inbound-folders"] }),
  });

  return (
    <div className="p-4 sm:p-6 space-y-4">
      <header className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
            <FolderSync className="h-6 w-6" /> Cloud-Inbox
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Verknüpfe einen Nextcloud-, OneDrive- oder Google-Drive-Freigabelink — neue Belege und Dokumente werden automatisch erfasst.
          </p>
        </div>
        <Button onClick={() => setAdding(true)}><Plus className="h-4 w-4 mr-1" /> Cloud-Ordner verbinden</Button>
      </header>

      <Card>
        <div className="divide-y divide-border">
          {(folders ?? []).map((f) => (
            <div key={f.id} className="p-4 flex flex-col sm:flex-row sm:items-center gap-3">
              <div className="flex-1 min-w-0">
                <div className="font-medium flex items-center gap-2 flex-wrap">
                  {f.name}
                  <Badge variant="outline">{INBOUND_TYPE_LABEL[f.type]}</Badge>
                  {f.enabled ? <Badge variant="success">aktiv</Badge> : <Badge variant="secondary">inaktiv</Badge>}
                </div>
                <div className="text-xs text-muted-foreground truncate" title={f.share_url}>{f.share_url}</div>
                <div className="text-xs mt-0.5 flex items-center flex-wrap gap-x-2 gap-y-1">
                  <span className="text-muted-foreground">
                    Alle {f.batch_interval_minutes} Min · Letzter Scan: {f.last_poll_at ? fmtRelative(f.last_poll_at) : "noch nie"}
                  </span>
                  {f.last_error && <span className="text-destructive">· Fehler: {f.last_error.slice(0, 80)}</span>}
                </div>
              </div>
              <div className="flex items-center gap-2 flex-wrap sm:flex-nowrap sm:ml-auto">
                <Switch
                  checked={f.enabled}
                  onCheckedChange={(v) => toggle.mutate({ id: f.id, enabled: !!v })}
                />
                <Button size="sm" variant="outline" onClick={() => test.mutate(f.id)}>
                  <TestTube className="h-3.5 w-3.5 mr-1" /> Testen
                </Button>
                <Button size="sm" variant="outline" onClick={() => scan.mutate(f.id)}>
                  <RefreshCw className="h-3.5 w-3.5 mr-1" /> Jetzt scannen
                </Button>
                <Button size="sm" variant="outline" onClick={() => setSelectedFolder(f)}>
                  Dateien
                </Button>
                <Button size="icon" variant="ghost" onClick={() => confirm("Cloud-Ordner wirklich entfernen?") && del.mutate(f.id)}>
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            </div>
          ))}
          {!folders?.length && (
            <div className="p-6 text-center text-muted-foreground">
              Noch keine Cloud-Ordner verbunden.
            </div>
          )}
        </div>
      </Card>

      {adding && (
        <FolderDialog
          orgs={orgs ?? []}
          defaultOrgId={orgId}
          onClose={() => setAdding(false)}
          onSaved={() => { setAdding(false); qc.invalidateQueries({ queryKey: ["inbound-folders"] }); }}
        />
      )}

      {selectedFolder && (
        <FolderFilesDialog
          folder={selectedFolder}
          onClose={() => setSelectedFolder(null)}
        />
      )}
    </div>
  );
}


function FolderDialog({
  orgs, defaultOrgId, onClose, onSaved,
}: {
  orgs: Organization[];
  defaultOrgId: number | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [organization_id, setOrgId] = useState<number | undefined>(defaultOrgId ?? orgs[0]?.id);
  const [type, setType] = useState<InboundFolderType>("nextcloud_share");
  const [name, setName] = useState("");
  const [share_url, setUrl] = useState("");
  const [password, setPassword] = useState("");
  const [batch_interval_minutes, setInterval] = useState(30);

  const create = useMutation({
    mutationFn: () => api("/inbound-folders", {
      method: "POST",
      body: { organization_id, type, name: name || "Cloud", share_url, password: password || undefined, batch_interval_minutes, enabled: true },
    }),
    onSuccess: (folder: any) => {
      // Trigger an immediate test + scan
      api(`/inbound-folders/${folder.id}/test`, { method: "POST" })
        .then((r: any) => toast({
          title: r.ok ? "Verbunden" : "Verbindung fehlgeschlagen",
          description: r.error,
          variant: r.ok ? "success" : "destructive",
        }))
        .finally(() => api(`/inbound-folders/${folder.id}/scan`, { method: "POST" }));
      onSaved();
    },
    onError: (e: any) => toast({ title: "Konnte nicht speichern", description: String(e?.message || e), variant: "destructive" }),
  });

  return (
    <Dialog open onOpenChange={onClose}>
      <DialogContent className="max-w-lg">
        <DialogHeader><DialogTitle>Cloud-Ordner verbinden</DialogTitle></DialogHeader>
        <div className="space-y-3">
          <div>
            <Label>Firma</Label>
            <Select value={String(organization_id ?? "")} onValueChange={(v) => setOrgId(Number(v))}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {orgs.map((o) => <SelectItem key={o.id} value={String(o.id)}>{o.name}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label>Typ</Label>
            <Select value={type} onValueChange={(v) => setType(v as InboundFolderType)}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="nextcloud_share">Nextcloud (Freigabelink)</SelectItem>
                <SelectItem value="onedrive_share">OneDrive (Freigabelink)</SelectItem>
                <SelectItem value="gdrive_share">Google Drive (Freigabelink)</SelectItem>
                <SelectItem value="local_mount">Lokaler Pfad (auf Server)</SelectItem>
              </SelectContent>
            </Select>
            <div className="text-xs text-muted-foreground mt-1">
              {type === "nextcloud_share" && "Beispiel: https://cloud.example.com/s/AbCdEf123 — Lesezugriff reicht."}
              {type === "onedrive_share" && "Beispiel: https://1drv.ms/f/s!Abc123 oder SharePoint-Link."}
              {type === "gdrive_share" && "Beispiel: https://drive.google.com/drive/folders/0AbcDef… — Freigabe auf \"Jeder mit dem Link\"."}
              {type === "local_mount" && "Pfad auf dem Server, z.B. /mnt/scans/sichersatt"}
            </div>
          </div>
          <div>
            <Label>Name</Label>
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="z.B. Scans SicherSatt" />
          </div>
          <div>
            <Label>Freigabelink / Pfad</Label>
            <Input value={share_url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…" />
          </div>
          {type === "nextcloud_share" && (
            <div>
              <Label>Passwort (nur falls Freigabe geschützt)</Label>
              <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
            </div>
          )}
          <div>
            <Label>Scan-Intervall (Min.)</Label>
            <Input type="number" min={1} value={batch_interval_minutes}
                   onChange={(e) => setInterval(parseInt(e.target.value) || 30)} />
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="ghost" onClick={onClose}>Abbrechen</Button>
            <Button onClick={() => create.mutate()} disabled={!share_url || !organization_id}>
              <Check className="h-4 w-4 mr-1" /> Verbinden &amp; testen
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}


function FolderFilesDialog({ folder, onClose }: { folder: InboundFolder; onClose: () => void }) {
  const { data: files } = useQuery<InboundFile[]>({
    queryKey: ["inbound-files", folder.id],
    queryFn: () => api(`/inbound-folders/${folder.id}/files`),
    refetchInterval: 5000,
  });
  return (
    <Dialog open onOpenChange={onClose}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FolderSync className="h-5 w-5" /> {folder.name} – letzte Dateien
          </DialogTitle>
        </DialogHeader>
        <div className="max-h-[60vh] overflow-y-auto">
          <table className="w-full text-sm">
            <thead className="text-xs text-muted-foreground border-b border-border">
              <tr>
                <th className="text-left py-2">Datei</th>
                <th className="text-left py-2">Status</th>
                <th className="text-left py-2">Empfangen</th>
                <th className="text-right py-2">Beleg</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {(files ?? []).map((f) => {
                const badge = STATUS_BADGE[f.status] ?? STATUS_BADGE.pending;
                return (
                  <tr key={f.id}>
                    <td className="py-2 truncate max-w-[280px]" title={f.filename}>{f.filename}</td>
                    <td className="py-2">
                      <Badge variant={badge.variant}>{badge.label}</Badge>
                      {f.error && <span className="text-xs text-destructive ml-2" title={f.error}>{f.error.slice(0, 60)}</span>}
                    </td>
                    <td className="py-2 text-muted-foreground">{f.processed_at ? fmtDateTime(f.processed_at) : "—"}</td>
                    <td className="py-2 text-right">
                      {f.receipt_id ? <Badge variant="outline">#{f.receipt_id}</Badge> : <span className="text-muted-foreground">—</span>}
                    </td>
                  </tr>
                );
              })}
              {!files?.length && (
                <tr><td colSpan={4} className="py-6 text-center text-muted-foreground">Noch keine Dateien — starte einen Scan oder warte den nächsten Zyklus ab.</td></tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="flex justify-end pt-2">
          <Button variant="ghost" onClick={onClose}><X className="h-4 w-4 mr-1" /> Schließen</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
