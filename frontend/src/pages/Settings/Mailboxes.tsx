import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../../lib/api";
import type { Mailbox, Organization } from "../../types";
import { Card } from "../../components/ui/card";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Switch } from "../../components/ui/switch";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "../../components/ui/dialog";
import { Plus, Edit3, Trash2, RefreshCw, Check } from "lucide-react";
import { fmtRelative } from "../../lib/format";
import { Badge } from "../../components/ui/badge";
import { toast } from "../../components/ui/toaster";

export default function Mailboxes() {
  const qc = useQueryClient();
  const { data: orgs } = useQuery<Organization[]>({ queryKey: ["orgs"], queryFn: () => api("/organizations") });
  const { data: mailboxes } = useQuery<Mailbox[]>({ queryKey: ["mailboxes"], queryFn: () => api("/mailboxes") });
  const [editing, setEditing] = useState<Mailbox | null>(null);
  const [creating, setCreating] = useState(false);

  const sync = useMutation({
    mutationFn: (id: number) => api(`/mailboxes/${id}/sync`, { method: "POST" }),
    onSuccess: () => toast({ title: "Synchronisation gestartet" }),
  });
  const del = useMutation({
    mutationFn: (id: number) => api(`/mailboxes/${id}`, { method: "DELETE" }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["mailboxes"] }); toast({ title: "Gelöscht" }); },
  });
  const test = useMutation({
    mutationFn: (id: number) => api<{ ok: boolean; error?: string }>(`/mailboxes/${id}/test`, { method: "POST" }),
    onSuccess: (r) => toast({ title: r.ok ? "Verbindung OK" : "Verbindung fehlgeschlagen", description: r.error, variant: r.ok ? "success" : "destructive" }),
  });

  return (
    <div className="p-4 sm:p-6 space-y-4">
      <header className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">Postfächer</h1>
        <Button onClick={() => setCreating(true)}><Plus className="h-4 w-4 mr-1" /> Postfach hinzufügen</Button>
      </header>
      <Card>
        <div className="divide-y divide-border">
          {(mailboxes ?? []).map((m) => (
            <div key={m.id} className="p-4 flex items-center gap-3">
              <div className="flex-1 min-w-0">
                <div className="font-medium truncate">{m.email}</div>
                <div className="text-xs text-muted-foreground">{m.imap_host}:{m.imap_port} · Ordner {m.folder} · alle {m.batch_interval_minutes} Min.</div>
                <div className="text-xs mt-0.5">
                  {m.enabled ? <Badge variant="success">aktiv</Badge> : <Badge variant="secondary">inaktiv</Badge>}
                  <span className="text-muted-foreground ml-2">Letzte Sync: {m.last_sync_at ? fmtRelative(m.last_sync_at) : "nie"}</span>
                  {m.last_error && <span className="text-destructive ml-2">· {m.last_error.slice(0, 80)}</span>}
                </div>
              </div>
              <Button size="sm" variant="outline" onClick={() => test.mutate(m.id)}>Testen</Button>
              <Button size="sm" variant="outline" onClick={() => sync.mutate(m.id)}><RefreshCw className="h-3.5 w-3.5 mr-1" /> Jetzt synchronisieren</Button>
              <Button size="icon" variant="ghost" onClick={() => setEditing(m)}><Edit3 className="h-4 w-4" /></Button>
              <Button size="icon" variant="ghost" onClick={() => confirm("Postfach wirklich löschen?") && del.mutate(m.id)}><Trash2 className="h-4 w-4" /></Button>
            </div>
          ))}
          {!mailboxes?.length && <div className="p-6 text-center text-muted-foreground">Noch keine Postfächer.</div>}
        </div>
      </Card>

      <MailboxDialog
        key={editing?.id ?? (creating ? "new" : "closed")}
        open={!!editing || creating}
        mb={editing}
        orgs={orgs ?? []}
        onClose={() => { setEditing(null); setCreating(false); }}
        onSaved={() => { qc.invalidateQueries({ queryKey: ["mailboxes"] }); setEditing(null); setCreating(false); }}
      />
    </div>
  );
}

function MailboxDialog({ open, mb, orgs, onClose, onSaved }: { open: boolean; mb: Mailbox | null; orgs: Organization[]; onClose: () => void; onSaved: () => void }) {
  const [organization_id, setOrg] = useState<number | undefined>(mb?.organization_id ?? orgs[0]?.id);
  const [email, setEmail] = useState(mb?.email ?? "");
  const [imap_host, setHost] = useState(mb?.imap_host ?? "imap.infomaniak.com");
  const [imap_port, setPort] = useState(mb?.imap_port ?? 993);
  const [imap_user, setUser] = useState(mb?.imap_user ?? "");
  const [imap_password, setPwd] = useState("");
  const [use_tls, setTls] = useState(mb?.use_tls ?? true);
  const [folder, setFolder] = useState(mb?.folder ?? "INBOX");
  const [batch_interval_minutes, setInterval] = useState(mb?.batch_interval_minutes ?? 30);
  const [enabled, setEnabled] = useState(mb?.enabled ?? true);

  const save = useMutation({
    mutationFn: async () => {
      const body: any = { organization_id, email, imap_host, imap_port, imap_user, use_tls, folder, batch_interval_minutes, enabled };
      if (imap_password) body.imap_password = imap_password;
      if (mb) return api(`/mailboxes/${mb.id}`, { method: "PATCH", body });
      return api("/mailboxes", { method: "POST", body });
    },
    onSuccess: () => { onSaved(); toast({ title: "Gespeichert", variant: "success" }); },
    onError: (e: any) => toast({ title: "Fehlgeschlagen", description: e.message, variant: "destructive" }),
  });

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader><DialogTitle>{mb ? "Postfach bearbeiten" : "Postfach hinzufügen"}</DialogTitle></DialogHeader>
        <div className="space-y-3">
          <div>
            <Label>Firma</Label>
            <Select value={organization_id ? String(organization_id) : undefined} onValueChange={(v) => setOrg(parseInt(v))}>
              <SelectTrigger><SelectValue placeholder="Auswählen…" /></SelectTrigger>
              <SelectContent>{orgs.map((o) => <SelectItem key={o.id} value={String(o.id)}>{o.name}</SelectItem>)}</SelectContent>
            </Select>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div><Label>E-Mail</Label><Input value={email} onChange={(e) => setEmail(e.target.value)} /></div>
            <div><Label>IMAP-Benutzer</Label><Input value={imap_user} onChange={(e) => setUser(e.target.value)} /></div>
            <div><Label>Host</Label><Input value={imap_host} onChange={(e) => setHost(e.target.value)} /></div>
            <div><Label>Port</Label><Input type="number" value={imap_port} onChange={(e) => setPort(parseInt(e.target.value) || 993)} /></div>
            <div className="col-span-2">
              <Label>Passwort {mb && <span className="text-xs text-muted-foreground">(leer lassen, um es zu behalten)</span>}</Label>
              <Input type="password" value={imap_password} onChange={(e) => setPwd(e.target.value)} />
            </div>
            <div><Label>Ordner</Label><Input value={folder} onChange={(e) => setFolder(e.target.value)} /></div>
            <div><Label>Intervall (Min.)</Label><Input type="number" value={batch_interval_minutes} onChange={(e) => setInterval(parseInt(e.target.value) || 30)} /></div>
          </div>
          <div className="flex items-center gap-6">
            <label className="flex items-center gap-2 text-sm"><Switch checked={use_tls} onCheckedChange={setTls} /> TLS/SSL</label>
            <label className="flex items-center gap-2 text-sm"><Switch checked={enabled} onCheckedChange={setEnabled} /> Aktiv</label>
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={onClose}>Abbrechen</Button>
            <Button onClick={() => save.mutate()}><Check className="h-4 w-4 mr-1" /> Speichern</Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
