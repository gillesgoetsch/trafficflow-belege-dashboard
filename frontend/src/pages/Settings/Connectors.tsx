import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../../lib/api";
import type {
  Connector,
  ConnectorMode,
  ConnectorPreviewResult,
  ConnectorType,
  Organization,
} from "../../types";
import { Card } from "../../components/ui/card";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
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
import { Plus, Trash2, TestTube, Plug, Eye, Settings2 } from "lucide-react";
import { useUi } from "../../store/ui";
import { toast } from "../../components/ui/toaster";
import { Badge } from "../../components/ui/badge";

const MODE_BADGE: Record<ConnectorMode, { label: string; cls: string }> = {
  off: {
    label: "Aus",
    cls: "bg-muted text-muted-foreground border-muted",
  },
  dry_run: {
    label: "Dry-Run",
    cls:
      "bg-yellow-500/15 text-yellow-700 dark:text-yellow-300 border-yellow-500/30",
  },
  live: {
    label: "Live",
    cls:
      "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border-emerald-500/30",
  },
};

export default function Connectors() {
  const orgId = useUi((s) => s.selectedOrgId);
  const qc = useQueryClient();
  const { data: connectors } = useQuery<Connector[]>({
    queryKey: ["connectors", orgId],
    queryFn: () =>
      api("/connectors", { query: { organization_id: orgId ?? undefined } }),
  });
  const { data: orgs } = useQuery<Organization[]>({
    queryKey: ["orgs"],
    queryFn: () => api("/organizations"),
  });

  const [adding, setAdding] = useState<ConnectorType | null>(null);
  const [editing, setEditing] = useState<Connector | null>(null);
  const [previewFor, setPreviewFor] = useState<Connector | null>(null);

  const del = useMutation({
    mutationFn: (id: number) => api(`/connectors/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["connectors"] }),
  });
  const test = useMutation({
    mutationFn: (id: number) =>
      api<{ ok: boolean; error?: string }>(`/connectors/${id}/test`, {
        method: "POST",
      }),
    onSuccess: (r) =>
      toast({
        title: r.ok ? "Verbindung OK" : "Verbindung fehlgeschlagen",
        description: r.error,
        variant: r.ok ? "success" : "destructive",
      }),
  });
  const setMode = useMutation({
    mutationFn: (vars: { c: Connector; mode: ConnectorMode }) =>
      api(`/connectors/${vars.c.id}`, {
        method: "PATCH",
        body: {
          organization_id: vars.c.organization_id,
          type: vars.c.type,
          name: vars.c.name,
          enabled: vars.c.enabled,
          mode: vars.mode,
        },
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["connectors"] }),
  });

  return (
    <div className="p-4 sm:p-6 space-y-4">
      <header className="flex items-center justify-between gap-3 flex-wrap">
        <h1 className="text-2xl font-semibold tracking-tight">Connectoren</h1>
        <div className="flex gap-2 flex-wrap">
          <Button variant="outline" onClick={() => setAdding("local")}>
            <Plus className="h-4 w-4 mr-1" /> Lokal
          </Button>
          <Button variant="outline" onClick={() => setAdding("onedrive")}>
            <Plus className="h-4 w-4 mr-1" /> OneDrive
          </Button>
          <Button variant="outline" onClick={() => setAdding("bexio")}>
            <Plus className="h-4 w-4 mr-1" /> Bexio
          </Button>
        </div>
      </header>

      <Card>
        <div className="divide-y divide-border">
          {(connectors ?? []).map((c) => {
            const badge = MODE_BADGE[c.mode];
            return (
              <div
                key={c.id}
                className="p-4 flex items-center gap-3 flex-wrap"
              >
                <Plug className="h-4 w-4 text-muted-foreground" />
                <div className="flex-1 min-w-[14rem]">
                  <div className="font-medium flex items-center gap-2 flex-wrap">
                    {c.name}
                    <Badge variant="outline">{c.type}</Badge>
                    <Badge variant="outline" className={badge.cls}>
                      {badge.label}
                    </Badge>
                    {c.type === "bexio" && c.mode === "live" && c.auto_book && (
                      <Badge
                        variant="outline"
                        className="bg-amber-500/15 text-amber-700 dark:text-amber-300 border-amber-500/30"
                      >
                        Auto-Book
                      </Badge>
                    )}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    Firma #{c.organization_id} ·{" "}
                    {c.enabled ? "aktiv" : "inaktiv"}
                  </div>
                </div>

                <div className="inline-flex rounded-md border border-input overflow-hidden text-sm">
                  {(["off", "dry_run", "live"] as ConnectorMode[]).map((m) => (
                    <button
                      key={m}
                      onClick={() => setMode.mutate({ c, mode: m })}
                      className={`px-2 py-1 transition-colors ${
                        c.mode === m
                          ? MODE_BADGE[m].cls + " font-medium"
                          : "bg-background hover:bg-muted"
                      }`}
                    >
                      {MODE_BADGE[m].label}
                    </button>
                  ))}
                </div>

                {c.type === "bexio" && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => setPreviewFor(c)}
                  >
                    <Eye className="h-3.5 w-3.5 mr-1" /> Test-Payload
                  </Button>
                )}
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => test.mutate(c.id)}
                >
                  <TestTube className="h-3.5 w-3.5 mr-1" /> Testen
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => setEditing(c)}
                >
                  <Settings2 className="h-3.5 w-3.5 mr-1" /> Bearbeiten
                </Button>
                <Button
                  size="icon"
                  variant="ghost"
                  onClick={() =>
                    confirm("Connector wirklich löschen?") && del.mutate(c.id)
                  }
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            );
          })}
          {!connectors?.length && (
            <div className="p-6 text-center text-muted-foreground">
              Noch keine Connectoren.
            </div>
          )}
        </div>
      </Card>

      {adding && (
        <ConnectorDialog
          type={adding}
          orgs={orgs ?? []}
          defaultOrgId={orgId}
          onClose={() => setAdding(null)}
          onSaved={() => {
            qc.invalidateQueries({ queryKey: ["connectors"] });
            setAdding(null);
          }}
        />
      )}
      {editing && (
        <EditConnectorDialog
          connector={editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            qc.invalidateQueries({ queryKey: ["connectors"] });
            setEditing(null);
          }}
        />
      )}
      {previewFor && (
        <PreviewDialog
          connector={previewFor}
          onClose={() => setPreviewFor(null)}
        />
      )}
    </div>
  );
}

function ModeSegmented({
  value,
  onChange,
}: {
  value: ConnectorMode;
  onChange: (m: ConnectorMode) => void;
}) {
  return (
    <div className="grid grid-cols-3 gap-2 mt-1">
      {(["off", "dry_run", "live"] as ConnectorMode[]).map((m) => (
        <button
          type="button"
          key={m}
          onClick={() => onChange(m)}
          className={`px-3 py-2 rounded border text-sm transition-colors ${
            value === m
              ? MODE_BADGE[m].cls + " border-transparent font-medium"
              : "border-input bg-background hover:bg-muted"
          }`}
        >
          {MODE_BADGE[m].label}
        </button>
      ))}
    </div>
  );
}

function ModeHelp({ mode }: { mode: ConnectorMode }) {
  const text =
    mode === "off"
      ? "Connector tut nichts — sicher, falls dieses Unternehmen den Connector nicht nutzt."
      : mode === "dry_run"
      ? "Baut die Anfrage zusammen und protokolliert sie, ohne etwas zu senden — ideal zum Validieren."
      : "Sendet Anfragen produktiv an die Ziel-API.";
  return <p className="text-xs text-muted-foreground mt-1">{text}</p>;
}

function ConnectorDialog({
  type,
  orgs,
  defaultOrgId,
  onClose,
  onSaved,
}: {
  type: ConnectorType;
  orgs: Organization[];
  defaultOrgId: number | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [organization_id, setOrg] = useState<number | undefined>(
    defaultOrgId ?? orgs[0]?.id,
  );
  const [name, setName] = useState(
    `${type[0].toUpperCase() + type.slice(1)} Ziel`,
  );
  const [mode, setMode] = useState<ConnectorMode>(
    type === "bexio" ? "dry_run" : "live",
  );
  const [auto_book, setAutoBook] = useState(false);
  const [config, setConfig] = useState<Record<string, any>>(
    type === "local"
      ? {
          base_path: "/data/local-mirror",
          subpath_template: "{org}/{year}/{month}",
        }
      : type === "onedrive"
      ? { folder_path: "/Belege" }
      : type === "bexio"
      ? {
          api_token: "",
          default_account_code: "",
          default_vat_code: "",
          default_currency: "CHF",
        }
      : {},
  );

  const save = useMutation({
    mutationFn: () =>
      api("/connectors", {
        method: "POST",
        body: {
          organization_id,
          type,
          name,
          enabled: true,
          mode,
          auto_book,
          config,
        },
      }),
    onSuccess: () => onSaved(),
    onError: (e: any) =>
      toast({
        title: "Fehlgeschlagen",
        description: e.message,
        variant: "destructive",
      }),
  });
  const startOneDrive = useMutation({
    mutationFn: () =>
      api<{ authorize_url: string }>(`/connectors/onedrive/authorize`, {
        query: { organization_id, name },
      }),
    onSuccess: (r) => {
      window.location.href = r.authorize_url;
    },
  });

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {type === "local"
              ? "Lokalen"
              : type === "onedrive"
              ? "OneDrive-"
              : "Bexio-"}{" "}
            Connector hinzufügen
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          {type === "bexio" && (
            <div className="rounded-md border border-yellow-500/30 bg-yellow-500/10 px-3 py-2 text-xs text-yellow-700 dark:text-yellow-300">
              <strong>Was passiert hier?</strong> Belege dieser Firma werden
              automatisch als kb_bill-Entwurf in Bexio angelegt (Lieferant,
              Betrag, Datum, Konto, PDF). Empfohlen: zuerst <em>Dry-Run</em>{" "}
              wählen — der Connector baut die volle Anfrage, sendet aber
              nichts. Im Sync-Inspector kannst du dann verifizieren, ob die
              Daten korrekt zugeordnet werden, und einzelne Belege per Klick
              auf <em>Live</em> hochstufen.
            </div>
          )}
          <div>
            <Label>Firma</Label>
            <Select
              value={organization_id ? String(organization_id) : undefined}
              onValueChange={(v) => setOrg(parseInt(v))}
            >
              <SelectTrigger>
                <SelectValue placeholder="Auswählen…" />
              </SelectTrigger>
              <SelectContent>
                {orgs.map((o) => (
                  <SelectItem key={o.id} value={String(o.id)}>
                    {o.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label>Name</Label>
            <Input value={name} onChange={(e) => setName(e.target.value)} />
          </div>

          <div>
            <Label>Modus</Label>
            <ModeSegmented value={mode} onChange={setMode} />
            <ModeHelp mode={mode} />
          </div>

          {type === "local" && (
            <>
              <div>
                <Label>Basis-Pfad</Label>
                <Input
                  value={config.base_path}
                  onChange={(e) =>
                    setConfig((c) => ({ ...c, base_path: e.target.value }))
                  }
                />
              </div>
              <div>
                <Label>Unterpfad-Vorlage</Label>
                <Input
                  value={config.subpath_template}
                  onChange={(e) =>
                    setConfig((c) => ({
                      ...c,
                      subpath_template: e.target.value,
                    }))
                  }
                />
              </div>
            </>
          )}
          {type === "onedrive" && (
            <>
              <div>
                <Label>Ordnerpfad</Label>
                <Input
                  value={config.folder_path}
                  onChange={(e) =>
                    setConfig((c) => ({ ...c, folder_path: e.target.value }))
                  }
                />
              </div>
              <p className="text-xs text-muted-foreground">
                OneDrive nutzt OAuth. Sie werden zu Microsoft weitergeleitet,
                um diesen Connector zu autorisieren.
              </p>
              <Button onClick={() => startOneDrive.mutate()} className="w-full">
                Mit Microsoft autorisieren
              </Button>
            </>
          )}
          {type === "bexio" && (
            <>
              <div>
                <Label>Bexio Personal Access Token (PAT)</Label>
                <Input
                  type="password"
                  value={config.api_token}
                  onChange={(e) =>
                    setConfig((c) => ({ ...c, api_token: e.target.value }))
                  }
                  placeholder="bxapi_…"
                />
              </div>
              <div className="grid grid-cols-3 gap-2">
                <div>
                  <Label>Standard-Konto</Label>
                  <Input
                    value={config.default_account_code}
                    onChange={(e) =>
                      setConfig((c) => ({
                        ...c,
                        default_account_code: e.target.value,
                      }))
                    }
                    placeholder="6510"
                  />
                </div>
                <div>
                  <Label>Standard-USt</Label>
                  <Input
                    value={config.default_vat_code}
                    onChange={(e) =>
                      setConfig((c) => ({
                        ...c,
                        default_vat_code: e.target.value,
                      }))
                    }
                    placeholder="VST077"
                  />
                </div>
                <div>
                  <Label>Währung</Label>
                  <Input
                    value={config.default_currency}
                    onChange={(e) =>
                      setConfig((c) => ({
                        ...c,
                        default_currency: e.target.value,
                      }))
                    }
                    placeholder="CHF"
                  />
                </div>
              </div>
              <div className="flex items-center justify-between rounded-md border border-input px-3 py-2">
                <div>
                  <div className="text-sm font-medium">
                    Auto-Book im Live-Modus
                  </div>
                  <div className="text-xs text-muted-foreground">
                    Bills sofort buchen. Aus = Belege bleiben als Entwurf zur
                    Prüfung in Bexio.
                  </div>
                </div>
                <Switch
                  checked={auto_book}
                  onCheckedChange={setAutoBook}
                />
              </div>
              <p className="text-xs text-muted-foreground">
                Token wird verschlüsselt gespeichert. Konto-Mappings können
                Sie unter „Anbieter“ pro Lieferant feinjustieren.
              </p>
            </>
          )}
          {type !== "onedrive" && (
            <div className="flex justify-end gap-2 pt-2">
              <Button variant="outline" onClick={onClose}>
                Abbrechen
              </Button>
              <Button onClick={() => save.mutate()}>Speichern</Button>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

function EditConnectorDialog({
  connector,
  onClose,
  onSaved,
}: {
  connector: Connector;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState(connector.name);
  const [mode, setMode] = useState<ConnectorMode>(connector.mode);
  const [auto_book, setAutoBook] = useState(connector.auto_book);
  const [config, setConfig] = useState<Record<string, any>>({});

  const save = useMutation({
    mutationFn: () =>
      api(`/connectors/${connector.id}`, {
        method: "PATCH",
        body: {
          organization_id: connector.organization_id,
          type: connector.type,
          name,
          enabled: connector.enabled,
          mode,
          auto_book,
          config,
        },
      }),
    onSuccess: () => onSaved(),
    onError: (e: any) =>
      toast({
        title: "Fehlgeschlagen",
        description: e.message,
        variant: "destructive",
      }),
  });

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{connector.name} bearbeiten</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div>
            <Label>Name</Label>
            <Input value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div>
            <Label>Modus</Label>
            <ModeSegmented value={mode} onChange={setMode} />
            <ModeHelp mode={mode} />
          </div>
          {connector.type === "bexio" && (
            <>
              <div>
                <Label>
                  Bexio PAT — leer lassen, um aktuellen Token zu behalten
                </Label>
                <Input
                  type="password"
                  value={config.api_token ?? ""}
                  onChange={(e) =>
                    setConfig((c) => ({ ...c, api_token: e.target.value }))
                  }
                />
              </div>
              <div className="grid grid-cols-3 gap-2">
                <div>
                  <Label>Standard-Konto</Label>
                  <Input
                    value={config.default_account_code ?? ""}
                    onChange={(e) =>
                      setConfig((c) => ({
                        ...c,
                        default_account_code: e.target.value,
                      }))
                    }
                  />
                </div>
                <div>
                  <Label>Standard-USt</Label>
                  <Input
                    value={config.default_vat_code ?? ""}
                    onChange={(e) =>
                      setConfig((c) => ({
                        ...c,
                        default_vat_code: e.target.value,
                      }))
                    }
                  />
                </div>
                <div>
                  <Label>Währung</Label>
                  <Input
                    value={config.default_currency ?? ""}
                    onChange={(e) =>
                      setConfig((c) => ({
                        ...c,
                        default_currency: e.target.value,
                      }))
                    }
                  />
                </div>
              </div>
              <div className="flex items-center justify-between rounded-md border border-input px-3 py-2">
                <div>
                  <div className="text-sm font-medium">
                    Auto-Book im Live-Modus
                  </div>
                  <div className="text-xs text-muted-foreground">
                    Bills sofort buchen statt als Entwurf belassen.
                  </div>
                </div>
                <Switch
                  checked={auto_book}
                  onCheckedChange={setAutoBook}
                />
              </div>
            </>
          )}
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={onClose}>
              Abbrechen
            </Button>
            <Button onClick={() => save.mutate()}>Speichern</Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function PreviewDialog({
  connector,
  onClose,
}: {
  connector: Connector;
  onClose: () => void;
}) {
  const { data, isLoading, error } = useQuery<ConnectorPreviewResult>({
    queryKey: ["connector-preview", connector.id],
    queryFn: () =>
      api(`/connectors/${connector.id}/preview`, { method: "POST" }),
    retry: false,
  });

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>Test-Payload · {connector.name}</DialogTitle>
        </DialogHeader>
        {isLoading && (
          <div className="p-6 text-muted-foreground">Erstelle Payload…</div>
        )}
        {error && (
          <div className="p-6 text-destructive">
            {(error as Error).message}
          </div>
        )}
        {data && (
          <div className="space-y-3 text-sm">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label>Beleg</Label>
                <div className="truncate">{data.receipt.filename}</div>
              </div>
              <div>
                <Label>Lieferant</Label>
                <div>{data.receipt.provider ?? "—"}</div>
              </div>
              <div>
                <Label>Betrag</Label>
                <div>
                  {data.receipt.amount ?? "—"} {data.receipt.currency ?? ""}
                </div>
              </div>
              <div>
                <Label>Beleg-Datum</Label>
                <div>{data.receipt.document_date ?? "—"}</div>
              </div>
              <div>
                <Label>Konto</Label>
                <div>
                  {data.receipt.account_code ?? (
                    <span className="text-amber-500">nicht zugeordnet</span>
                  )}
                </div>
              </div>
              <div>
                <Label>USt-Code</Label>
                <div>{data.receipt.vat_code ?? "—"}</div>
              </div>
            </div>
            <div>
              <Label>Anfrage-Payload (würde an Bexio gesendet)</Label>
              <pre className="mt-1 max-h-80 overflow-auto rounded-md border border-input bg-muted/50 p-3 text-xs font-mono">
                {JSON.stringify(data.result.request_payload, null, 2)}
              </pre>
            </div>
            {data.result.error && (
              <div className="text-destructive text-xs">
                {data.result.error}
              </div>
            )}
          </div>
        )}
        <div className="flex justify-end pt-2">
          <Button variant="outline" onClick={onClose}>
            Schließen
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
