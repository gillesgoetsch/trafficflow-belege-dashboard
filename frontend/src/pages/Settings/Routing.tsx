import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../../lib/api";
import type { Organization } from "../../types";
import { Card } from "../../components/ui/card";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Badge } from "../../components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { Plus, Trash2 } from "lucide-react";
import { toast } from "../../components/ui/toaster";

interface Rule {
  id: number;
  organization_id: number;
  match_type: "body_contains" | "sender_contains" | "subject_contains" | "sender_domain";
  match_value: string;
  priority: number;
}

const MATCH_TYPES: Rule["match_type"][] = ["body_contains", "sender_contains", "subject_contains", "sender_domain"];

export default function Routing() {
  const qc = useQueryClient();
  const { data: rules } = useQuery<Rule[]>({ queryKey: ["org-routing"], queryFn: () => api("/org-routing") });
  const { data: orgs } = useQuery<Organization[]>({ queryKey: ["orgs"], queryFn: () => api("/organizations") });
  const [orgId, setOrgId] = useState<number | null>(null);
  const [mt, setMt] = useState<Rule["match_type"]>("body_contains");
  const [mv, setMv] = useState("");

  const add = useMutation({
    mutationFn: () => api("/org-routing", { method: "POST", body: { organization_id: orgId, match_type: mt, match_value: mv, priority: 100 } }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["org-routing"] }); setMv(""); toast({ title: "Rule added", variant: "success" }); },
    onError: (e: any) => toast({ title: "Failed", description: e.message, variant: "destructive" }),
  });
  const del = useMutation({
    mutationFn: (id: number) => api(`/org-routing/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["org-routing"] }),
  });

  return (
    <div className="p-4 sm:p-6 space-y-4">
      <h1 className="text-2xl font-semibold tracking-tight">Organization routing</h1>
      <p className="text-sm text-muted-foreground max-w-3xl">
        When one mailbox receives bills for multiple companies, these rules
        decide which organization a receipt belongs to. The matcher is a
        case-insensitive substring on the chosen field. Higher priority wins
        first. Default: the mailbox's own organization.
      </p>

      <Card className="p-4">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-2 items-end">
          <div>
            <Label className="text-xs">Organization</Label>
            <Select value={orgId ? String(orgId) : undefined} onValueChange={(v) => setOrgId(parseInt(v))}>
              <SelectTrigger><SelectValue placeholder="Choose…" /></SelectTrigger>
              <SelectContent>{(orgs ?? []).map((o) => <SelectItem key={o.id} value={String(o.id)}>{o.name}</SelectItem>)}</SelectContent>
            </Select>
          </div>
          <div>
            <Label className="text-xs">Match type</Label>
            <Select value={mt} onValueChange={(v) => setMt(v as Rule["match_type"])}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>{MATCH_TYPES.map((t) => <SelectItem key={t} value={t}>{t}</SelectItem>)}</SelectContent>
            </Select>
          </div>
          <div>
            <Label className="text-xs">Value (substring)</Label>
            <Input value={mv} placeholder="e.g. kingnature, FIMS, leckker" onChange={(e) => setMv(e.target.value)} />
          </div>
          <Button onClick={() => add.mutate()} disabled={!orgId || !mv}><Plus className="h-4 w-4 mr-1" /> Add rule</Button>
        </div>
      </Card>

      <Card>
        <div className="divide-y divide-border">
          {(rules ?? []).map((r) => (
            <div key={r.id} className="p-3 flex items-center gap-3 text-sm">
              <Badge variant="secondary">{(orgs ?? []).find((o) => o.id === r.organization_id)?.name || `#${r.organization_id}`}</Badge>
              <Badge variant="outline">{r.match_type}</Badge>
              <span className="font-mono">{r.match_value}</span>
              <span className="text-muted-foreground">priority {r.priority}</span>
              <div className="ml-auto">
                <Button size="icon" variant="ghost" onClick={() => del.mutate(r.id)}><Trash2 className="h-4 w-4" /></Button>
              </div>
            </div>
          ))}
          {!rules?.length && <div className="p-6 text-center text-muted-foreground">No routing rules yet.</div>}
        </div>
      </Card>
    </div>
  );
}
