import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../store/auth";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import { Receipt } from "lucide-react";
import { toast } from "../components/ui/toaster";

export default function Login() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [otp, setOtp] = useState("");
  const [needsOtp, setNeedsOtp] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const login = useAuth((s) => s.login);
  const user = useAuth((s) => s.user);
  const hydrate = useAuth((s) => s.hydrate);
  const navigate = useNavigate();

  useEffect(() => { hydrate(); }, [hydrate]);
  useEffect(() => { if (user) navigate("/"); }, [user, navigate]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      await login(email, password, otp || undefined);
      navigate("/");
    } catch (err: any) {
      if (String(err.message || "").toLowerCase().includes("otp")) {
        setNeedsOtp(true);
        toast({ title: "OTP-Code erforderlich", description: "Bitte Code aus der Authenticator-App eingeben." });
      } else {
        toast({ title: "Anmeldung fehlgeschlagen", description: err.message || "", variant: "destructive" });
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-dvh w-full flex items-center justify-center bg-background p-4">
      <Card className="w-full max-w-sm">
        <CardHeader className="text-center">
          <div className="flex justify-center mb-2">
            <div className="h-10 w-10 rounded-lg bg-primary/15 text-primary flex items-center justify-center">
              <Receipt className="h-5 w-5" />
            </div>
          </div>
          <CardTitle>Belege-Hub</CardTitle>
          <CardDescription>Bitte anmelden</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={submit} className="space-y-3">
            <div>
              <Label htmlFor="email">E-Mail</Label>
              <Input id="email" type="email" required autoFocus value={email} onChange={(e) => setEmail(e.target.value)} className="mt-1" />
            </div>
            <div>
              <Label htmlFor="password">Passwort</Label>
              <Input id="password" type="password" required value={password} onChange={(e) => setPassword(e.target.value)} className="mt-1" />
            </div>
            {needsOtp && (
              <div>
                <Label htmlFor="otp">6-stelliger Code</Label>
                <Input id="otp" inputMode="numeric" maxLength={6} value={otp} onChange={(e) => setOtp(e.target.value)} className="mt-1" />
              </div>
            )}
            <Button className="w-full" type="submit" disabled={submitting}>
              {submitting ? "Anmelden…" : "Anmelden"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
