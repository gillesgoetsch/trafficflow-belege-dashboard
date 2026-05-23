import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../../lib/api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { toast } from "../../components/ui/toaster";
import { useAuth } from "../../store/auth";

export default function Account() {
  const user = useAuth((s) => s.user);
  const hydrate = useAuth((s) => s.hydrate);
  const qc = useQueryClient();

  const [cur, setCur] = useState("");
  const [nw, setNw] = useState("");
  const change = useMutation({
    mutationFn: () => api("/auth/change-password", { method: "POST", body: { current_password: cur, new_password: nw } }),
    onSuccess: () => { toast({ title: "Passwort aktualisiert", variant: "success" }); setCur(""); setNw(""); },
    onError: (e: any) => toast({ title: "Fehlgeschlagen", description: e.message, variant: "destructive" }),
  });

  const enroll = useMutation({
    mutationFn: () => api<{ secret: string; qr_data_url: string; uri: string }>("/auth/totp/enroll", { method: "POST" }),
  });
  const [otp, setOtp] = useState("");
  const confirm = useMutation({
    mutationFn: () => api("/auth/totp/confirm", { method: "POST", body: { code: otp } }),
    onSuccess: () => { toast({ title: "2-Faktor aktiviert", variant: "success" }); hydrate(); enroll.reset(); setOtp(""); },
    onError: (e: any) => toast({ title: "Fehlgeschlagen", description: e.message, variant: "destructive" }),
  });
  const disable = useMutation({
    mutationFn: () => api("/auth/totp/disable", { method: "POST" }),
    onSuccess: () => { toast({ title: "2-Faktor deaktiviert", variant: "success" }); hydrate(); },
  });

  return (
    <div className="p-4 sm:p-6 max-w-2xl space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Konto</CardTitle>
          <CardDescription>Angemeldet als {user?.email}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div><Label>Aktuelles Passwort</Label><Input type="password" value={cur} onChange={(e) => setCur(e.target.value)} /></div>
          <div><Label>Neues Passwort</Label><Input type="password" value={nw} onChange={(e) => setNw(e.target.value)} /></div>
          <Button disabled={!cur || nw.length < 8} onClick={() => change.mutate()}>Passwort ändern</Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Zwei-Faktor (TOTP)</CardTitle>
          <CardDescription>Optional. Ergänzt die Anmeldung um einen zweiten Faktor.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {user?.totp_enabled ? (
            <Button variant="destructive" onClick={() => disable.mutate()}>2-Faktor deaktivieren</Button>
          ) : enroll.data ? (
            <div className="space-y-3">
              <img src={enroll.data.qr_data_url} alt="QR" className="border border-border rounded p-2 bg-white inline-block" />
              <p className="text-xs text-muted-foreground">Mit Authenticator-App scannen, dann den 6-stelligen Code eingeben:</p>
              <div className="flex gap-2 items-end">
                <Input maxLength={6} value={otp} onChange={(e) => setOtp(e.target.value)} className="w-32" />
                <Button onClick={() => confirm.mutate()}>Aktivieren</Button>
              </div>
            </div>
          ) : (
            <Button onClick={() => enroll.mutate()}>Einrichten</Button>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
