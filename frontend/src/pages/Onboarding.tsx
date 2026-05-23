import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { CheckCircle2, ArrowRight } from "lucide-react";
import { toast } from "../components/ui/toaster";

type State = {
  org: { name: string; primary_email: string; default_currency: string; timezone: string };
  mailbox: { email: string; imap_host: string; imap_port: number; imap_user: string; imap_password: string; folder: string };
  orgId?: number;
  mailboxId?: number;
};

export default function Onboarding() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [step, setStep] = useState(1);
  const [state, setState] = useState<State>({
    org: { name: "", primary_email: "", default_currency: "CHF", timezone: "Europe/Zurich" },
    mailbox: { email: "", imap_host: "imap.infomaniak.com", imap_port: 993, imap_user: "", imap_password: "", folder: "INBOX" },
  });

  const createOrg = useMutation({
    mutationFn: () => api<{ id: number }>("/organizations", { method: "POST", body: state.org }),
    onSuccess: (r) => { setState((s) => ({ ...s, orgId: r.id })); qc.invalidateQueries({ queryKey: ["orgs"] }); setStep(2); },
    onError: (e: any) => toast({ title: "Fehlgeschlagen", description: e.message, variant: "destructive" }),
  });

  const createMailbox = useMutation({
    mutationFn: () => api<{ id: number }>("/mailboxes", { method: "POST", body: { organization_id: state.orgId, ...state.mailbox, use_tls: true, batch_interval_minutes: 30, enabled: true } }),
    onSuccess: (r) => { setState((s) => ({ ...s, mailboxId: r.id })); setStep(3); },
    onError: (e: any) => toast({ title: "Fehlgeschlagen", description: e.message, variant: "destructive" }),
  });

  const testMailbox = useMutation({
    mutationFn: () => api<{ ok: boolean; error?: string }>(`/mailboxes/${state.mailboxId}/test`, { method: "POST" }),
    onSuccess: (r) => toast({ title: r.ok ? "Verbindung OK" : "Verbindung fehlgeschlagen", description: r.error, variant: r.ok ? "success" : "destructive" }),
  });

  const triggerSync = useMutation({
    mutationFn: () => api(`/mailboxes/${state.mailboxId}/sync`, { method: "POST" }),
    onSuccess: () => { toast({ title: "Test-Scan gestartet", variant: "success" }); setStep(5); },
  });

  return (
    <div className="p-4 sm:p-6 max-w-2xl mx-auto space-y-4">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Einrichtungsassistent</h1>
        <p className="text-sm text-muted-foreground">Neue Firma in unter 15 Minuten einrichten.</p>
      </header>

      <Stepper step={step} />

      {step === 1 && (
        <Card>
          <CardHeader><CardTitle>1. Firmen-Daten</CardTitle><CardDescription>Name und E-Mail-Adresse, an die Belege gesendet werden.</CardDescription></CardHeader>
          <CardContent className="space-y-3">
            <div><Label>Firmenname</Label><Input value={state.org.name} onChange={(e) => setState((s) => ({ ...s, org: { ...s.org, name: e.target.value } }))} /></div>
            <div><Label>Haupt-E-Mail</Label><Input type="email" value={state.org.primary_email} onChange={(e) => setState((s) => ({ ...s, org: { ...s.org, primary_email: e.target.value } }))} /></div>
            <div className="grid grid-cols-2 gap-2">
              <div><Label>Währung</Label><Input value={state.org.default_currency} onChange={(e) => setState((s) => ({ ...s, org: { ...s.org, default_currency: e.target.value.toUpperCase() } }))} /></div>
              <div><Label>Zeitzone</Label><Input value={state.org.timezone} onChange={(e) => setState((s) => ({ ...s, org: { ...s.org, timezone: e.target.value } }))} /></div>
            </div>
            <Button onClick={() => createOrg.mutate()} disabled={!state.org.name || !state.org.primary_email}>Weiter <ArrowRight className="h-4 w-4 ml-1" /></Button>
          </CardContent>
        </Card>
      )}

      {step === 2 && (
        <Card>
          <CardHeader><CardTitle>2. Postfach verbinden</CardTitle><CardDescription>IMAP-Zugangsdaten. Diese werden verschlüsselt gespeichert.</CardDescription></CardHeader>
          <CardContent className="space-y-3">
            <div className="grid grid-cols-2 gap-2">
              <div><Label>E-Mail</Label><Input value={state.mailbox.email} onChange={(e) => setState((s) => ({ ...s, mailbox: { ...s.mailbox, email: e.target.value, imap_user: s.mailbox.imap_user || e.target.value } }))} /></div>
              <div><Label>IMAP-Benutzer</Label><Input value={state.mailbox.imap_user} onChange={(e) => setState((s) => ({ ...s, mailbox: { ...s.mailbox, imap_user: e.target.value } }))} /></div>
              <div><Label>Host</Label><Input value={state.mailbox.imap_host} onChange={(e) => setState((s) => ({ ...s, mailbox: { ...s.mailbox, imap_host: e.target.value } }))} /></div>
              <div><Label>Port</Label><Input type="number" value={state.mailbox.imap_port} onChange={(e) => setState((s) => ({ ...s, mailbox: { ...s.mailbox, imap_port: parseInt(e.target.value) || 993 } }))} /></div>
              <div className="col-span-2"><Label>Passwort / App-Passwort</Label><Input type="password" value={state.mailbox.imap_password} onChange={(e) => setState((s) => ({ ...s, mailbox: { ...s.mailbox, imap_password: e.target.value } }))} /></div>
            </div>
            <Button onClick={() => createMailbox.mutate()} disabled={!state.mailbox.email || !state.mailbox.imap_password}>Weiter <ArrowRight className="h-4 w-4 ml-1" /></Button>
          </CardContent>
        </Card>
      )}

      {step === 3 && (
        <Card>
          <CardHeader><CardTitle>3. Verbindung prüfen</CardTitle><CardDescription>Kurzer Test vor dem Import.</CardDescription></CardHeader>
          <CardContent className="space-y-3">
            <Button onClick={() => testMailbox.mutate()}>Verbindung testen</Button>
            <Button variant="ghost" onClick={() => setStep(4)}>Überspringen <ArrowRight className="h-4 w-4 ml-1" /></Button>
          </CardContent>
        </Card>
      )}

      {step === 4 && (
        <Card>
          <CardHeader><CardTitle>4. Erst-Import</CardTitle><CardDescription>Wir holen die letzten E-Mails und klassifizieren sie.</CardDescription></CardHeader>
          <CardContent className="space-y-3">
            <p className="text-sm text-muted-foreground">Läuft im Hintergrund und kann einige Minuten dauern.</p>
            <Button onClick={() => triggerSync.mutate()}>Erst-Import starten</Button>
          </CardContent>
        </Card>
      )}

      {step === 5 && (
        <Card>
          <CardHeader><CardTitle className="flex items-center gap-2"><CheckCircle2 className="h-5 w-5 text-emerald-400" /> Fertig</CardTitle><CardDescription>Ihre Firma ist bereit. Connectoren einrichten oder direkt zu den Belegen.</CardDescription></CardHeader>
          <CardContent className="space-y-2">
            <Button onClick={() => navigate("/settings/connectors")}>Connectoren einrichten</Button>
            <Button variant="outline" className="ml-2" onClick={() => navigate("/inbox")}>Belege öffnen</Button>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function Stepper({ step }: { step: number }) {
  const steps = ["Firma", "Postfach", "Prüfung", "Erst-Import", "Fertig"];
  return (
    <div className="flex items-center justify-between text-xs text-muted-foreground">
      {steps.map((label, i) => (
        <div key={label} className={`flex items-center gap-2 ${step >= i + 1 ? "text-foreground" : ""}`}>
          <div className={`h-6 w-6 rounded-full border flex items-center justify-center text-[11px] ${step >= i + 1 ? "border-primary bg-primary/10 text-primary" : "border-border"}`}>{i + 1}</div>
          <span className="hidden sm:inline">{label}</span>
          {i < steps.length - 1 && <span className="w-6 h-px bg-border" />}
        </div>
      ))}
    </div>
  );
}
