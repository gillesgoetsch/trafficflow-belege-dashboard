import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../../lib/api";
import type { Organization } from "../../types";
import { Card } from "../../components/ui/card";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "../../components/ui/dialog";
import { Plus, Trash2, Edit3 } from "lucide-react";
import { toast } from "../../components/ui/toaster";

export default function Organizations() {
  const qc = useQueryClient();
  const { data: orgs } = useQuery<Organization[]>({ queryKey: ["orgs"], queryFn: () => api("/organizations") });
  const [editing, setEditing] = useState<Organization | null>(null);
  const [creating, setCreating] = useState(false);

  const save = useMutation({
    mutationFn: async (body: Partial<Organization>) => {
      if (editing) return api(`/organizations/${editing.id}`, { method: "PATCH", body });
      return api("/organizations", { method: "POST", body });
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["orgs"] }); setEditing(null); setCreating(false); toast({ title: "Gespeichert", variant: "success" }); },
    onError: (e: any) => toast({ title: "Fehlgeschlagen", description: e.message, variant: "destructive" }),
  });

  const del = useMutation({
    mutationFn: (id: number) => api(`/organizations/${id}`, { method: "DELETE" }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["orgs"] }); toast({ title: "Gelöscht", variant: "success" }); },
  });

  return (
    <div className="p-4 sm:p-6 space-y-4">
      <header className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">Firmen</h1>
        <Button onClick={() => setCreating(true)}><Plus className="h-4 w-4 mr-1" /> Hinzufügen</Button>
      </header>

      <Card>
        <div className="divide-y divide-border">
          {(orgs ?? []).map((o) => (
            <div key={o.id} className="p-4 flex items-center gap-3">
              <div className="flex-1">
                <div className="font-medium">{o.name}</div>
                <div className="text-xs text-muted-foreground">{o.primary_email} · {o.default_currency} · {o.timezone}</div>
              </div>
              <Button size="icon" variant="ghost" onClick={() => setEditing(o)}><Edit3 className="h-4 w-4" /></Button>
              <Button size="icon" variant="ghost" onClick={() => confirm("Firma wirklich löschen?") && del.mutate(o.id)}><Trash2 className="h-4 w-4" /></Button>
            </div>
          ))}
          {!orgs?.length && <div className="p-6 text-center text-muted-foreground">Noch keine Firmen vorhanden.</div>}
        </div>
      </Card>

      <OrganizationDialog
        key={editing?.id ?? (creating ? "new" : "closed")}
        open={!!editing || creating}
        org={editing}
        onClose={() => { setEditing(null); setCreating(false); }}
        onSave={(body) => save.mutate(body)}
      />
    </div>
  );
}

function OrganizationDialog({ open, org, onClose, onSave }: { open: boolean; org: Organization | null; onClose: () => void; onSave: (body: any) => void }) {
  const [name, setName] = useState(org?.name ?? "");
  const [primary_email, setEmail] = useState(org?.primary_email ?? "");
  const [default_currency, setCurrency] = useState(org?.default_currency ?? "CHF");
  const [timezone, setTimezone] = useState(org?.timezone ?? "Europe/Zurich");
  const [filename_template, setTemplate] = useState(org?.filename_template ?? "{date}_{provider}_{client}_{amount}-{currency}");

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader><DialogTitle>{org ? "Firma bearbeiten" : "Neue Firma"}</DialogTitle></DialogHeader>
        <div className="space-y-3">
          <div><Label>Name</Label><Input value={name} onChange={(e) => setName(e.target.value)} /></div>
          <div><Label>Haupt-E-Mail</Label><Input type="email" value={primary_email} onChange={(e) => setEmail(e.target.value)} /></div>
          <div className="grid grid-cols-2 gap-2">
            <div><Label>Währung</Label><Input value={default_currency} onChange={(e) => setCurrency(e.target.value.toUpperCase())} /></div>
            <div><Label>Zeitzone</Label><Input value={timezone} onChange={(e) => setTimezone(e.target.value)} /></div>
          </div>
          <div>
            <Label>Dateinamen-Vorlage</Label>
            <Input value={filename_template} onChange={(e) => setTemplate(e.target.value)} />
            <p className="text-xs text-muted-foreground mt-1">Platzhalter: {"{date}"}, {"{provider}"}, {"{client}"}, {"{amount}"}, {"{currency}"}, {"{invoice_number}"}</p>
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={onClose}>Abbrechen</Button>
            <Button onClick={() => onSave({ name, primary_email, default_currency, timezone, filename_template })}>Speichern</Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
