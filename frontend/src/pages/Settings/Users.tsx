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
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "../../components/ui/dialog";
import { Plus, Trash2, Edit3 } from "lucide-react";
import { toast } from "../../components/ui/toaster";

interface UserRow {
  id: number;
  email: string;
  role: "admin" | "accountant";
  is_active: boolean;
  organization_ids: number[];
}

export default function Users() {
  const qc = useQueryClient();
  const { data: users } = useQuery<UserRow[]>({ queryKey: ["users"], queryFn: () => api("/users") });
  const { data: orgs } = useQuery<Organization[]>({ queryKey: ["orgs"], queryFn: () => api("/organizations") });
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<UserRow | null>(null);

  const del = useMutation({
    mutationFn: (id: number) => api(`/users/${id}`, { method: "DELETE" }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["users"] }); toast({ title: "Deleted" }); },
    onError: (e: any) => toast({ title: "Failed", description: e.message, variant: "destructive" }),
  });

  return (
    <div className="p-4 sm:p-6 space-y-4">
      <header className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">Users</h1>
        <Button onClick={() => setCreating(true)}><Plus className="h-4 w-4 mr-1" /> Add user</Button>
      </header>
      <p className="text-sm text-muted-foreground">
        Admin users can manage everything. Accountant users see only the organizations you grant them
        — they can browse receipts, edit metadata, mark booked, and export downloads/CSV.
      </p>

      <Card>
        <div className="divide-y divide-border">
          {(users ?? []).map((u) => (
            <div key={u.id} className="p-4 flex items-center gap-3">
              <div className="flex-1 min-w-0">
                <div className="font-medium">{u.email}</div>
                <div className="text-xs text-muted-foreground flex items-center gap-1.5 mt-1">
                  <Badge variant={u.role === "admin" ? "default" : "secondary"}>{u.role}</Badge>
                  {!u.is_active && <Badge variant="destructive">disabled</Badge>}
                  {u.role !== "admin" && (
                    <>
                      <span>·</span>
                      {u.organization_ids.length === 0
                        ? <span className="text-warning">No org access</span>
                        : <span>Orgs: {u.organization_ids.map((id) => orgs?.find((o) => o.id === id)?.name || `#${id}`).join(", ")}</span>}
                    </>
                  )}
                </div>
              </div>
              <Button size="icon" variant="ghost" onClick={() => setEditing(u)}><Edit3 className="h-4 w-4" /></Button>
              <Button size="icon" variant="ghost" onClick={() => confirm(`Delete ${u.email}?`) && del.mutate(u.id)}><Trash2 className="h-4 w-4" /></Button>
            </div>
          ))}
          {!users?.length && <div className="p-6 text-center text-muted-foreground">No users.</div>}
        </div>
      </Card>

      {(creating || editing) && (
        <UserDialog
          key={editing?.id ?? "new"}
          user={editing}
          orgs={orgs ?? []}
          onClose={() => { setCreating(false); setEditing(null); }}
          onSaved={() => { qc.invalidateQueries({ queryKey: ["users"] }); setCreating(false); setEditing(null); }}
        />
      )}
    </div>
  );
}

function UserDialog({ user, orgs, onClose, onSaved }: {
  user: UserRow | null; orgs: Organization[]; onClose: () => void; onSaved: () => void;
}) {
  const [email, setEmail] = useState(user?.email ?? "");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<"admin" | "accountant">(user?.role ?? "accountant");
  const [orgIds, setOrgIds] = useState<Set<number>>(new Set(user?.organization_ids ?? []));
  const [isActive, setIsActive] = useState(user?.is_active ?? true);

  const save = useMutation({
    mutationFn: async () => {
      const body: any = { role, organization_ids: Array.from(orgIds), is_active: isActive };
      if (user) {
        if (password) body.password = password;
        return api(`/users/${user.id}`, { method: "PATCH", body });
      }
      if (!password) throw new Error("Password required");
      return api("/users", { method: "POST", body: { email, password, role, organization_ids: Array.from(orgIds) } });
    },
    onSuccess: () => { onSaved(); toast({ title: "Saved", variant: "success" }); },
    onError: (e: any) => toast({ title: "Failed", description: e.message, variant: "destructive" }),
  });

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader><DialogTitle>{user ? "Edit user" : "Add user"}</DialogTitle></DialogHeader>
        <div className="space-y-3">
          <div><Label>Email</Label><Input type="email" value={email} disabled={!!user} onChange={(e) => setEmail(e.target.value)} /></div>
          <div>
            <Label>{user ? "New password (leave blank to keep)" : "Password"}</Label>
            <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
          </div>
          <div>
            <Label>Role</Label>
            <Select value={role} onValueChange={(v) => setRole(v as any)}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="admin">Admin — full access</SelectItem>
                <SelectItem value="accountant">Accountant — selected orgs only</SelectItem>
              </SelectContent>
            </Select>
          </div>
          {role === "accountant" && (
            <div>
              <Label>Allowed organizations</Label>
              <div className="space-y-1 mt-1">
                {orgs.map((o) => (
                  <label key={o.id} className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={orgIds.has(o.id)}
                      onChange={(e) => {
                        const s = new Set(orgIds);
                        if (e.target.checked) s.add(o.id); else s.delete(o.id);
                        setOrgIds(s);
                      }}
                    /> {o.name}
                  </label>
                ))}
              </div>
            </div>
          )}
          {user && (
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={isActive} onChange={(e) => setIsActive(e.target.checked)} /> Active
            </label>
          )}
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={onClose}>Cancel</Button>
            <Button onClick={() => save.mutate()}>Save</Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
