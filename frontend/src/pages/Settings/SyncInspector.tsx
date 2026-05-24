import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import {
  ChevronRight,
  Copy,
  ExternalLink,
  PlayCircle,
  RefreshCcw,
} from "lucide-react";
import { api } from "../../lib/api";
import type {
  Connector,
  ConnectorMode,
  Organization,
  SyncStatus,
  SyncTargetDetail,
  SyncTargetList,
  SyncTargetRow,
} from "../../types";
import { Card } from "../../components/ui/card";
import { Button } from "../../components/ui/button";
import { Badge } from "../../components/ui/badge";
import { Label } from "../../components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../../components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "../../components/ui/dialog";
import { toast } from "../../components/ui/toaster";
import { useUi } from "../../store/ui";

const MODE_CLS: Record<ConnectorMode, string> = {
  off: "bg-muted text-muted-foreground border-muted",
  dry_run:
    "bg-yellow-500/15 text-yellow-700 dark:text-yellow-300 border-yellow-500/30",
  live:
    "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border-emerald-500/30",
};

const STATUS_CLS: Record<SyncStatus, string> = {
  pending: "bg-muted text-muted-foreground",
  synced:
    "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border-emerald-500/30",
  failed:
    "bg-rose-500/15 text-rose-700 dark:text-rose-300 border-rose-500/30",
  skipped: "bg-muted text-muted-foreground",
  dry_run_ok:
    "bg-yellow-500/15 text-yellow-700 dark:text-yellow-300 border-yellow-500/30",
};

const STATUS_LABEL: Record<SyncStatus, string> = {
  pending: "Wartet",
  synced: "Synchronisiert",
  failed: "Fehlgeschlagen",
  skipped: "Übersprungen",
  dry_run_ok: "Dry-Run OK",
};

export default function SyncInspector() {
  const orgId = useUi((s) => s.selectedOrgId);
  const qc = useQueryClient();

  const [statusFilter, setStatusFilter] = useState<SyncStatus | "">("");
  const [modeFilter, setModeFilter] = useState<ConnectorMode | "">("");
  const [connectorFilter, setConnectorFilter] = useState<number | "">("");
  const [openId, setOpenId] = useState<number | null>(null);

  const { data: orgs } = useQuery<Organization[]>({
    queryKey: ["orgs"],
    queryFn: () => api("/organizations"),
  });
  const { data: connectors } = useQuery<Connector[]>({
    queryKey: ["connectors", orgId],
    queryFn: () =>
      api("/connectors", { query: { organization_id: orgId ?? undefined } }),
  });

  const list = useQuery<SyncTargetList>({
    queryKey: [
      "sync-targets",
      orgId,
      connectorFilter,
      statusFilter,
      modeFilter,
    ],
    queryFn: () =>
      api("/sync-targets", {
        query: {
          organization_id: orgId ?? undefined,
          connector_id: connectorFilter || undefined,
          status: statusFilter || undefined,
          mode: modeFilter || undefined,
          page_size: 100,
        },
      }),
  });

  const promote = useMutation({
    mutationFn: (id: number) =>
      api(`/sync-targets/${id}/promote`, { method: "POST" }),
    onSuccess: () => {
      toast({
        title: "Live-Lauf in Warteschlange",
        description: "Wird in Kürze ausgeführt.",
        variant: "success",
      });
      qc.invalidateQueries({ queryKey: ["sync-targets"] });
    },
    onError: (e: any) =>
      toast({
        title: "Fehlgeschlagen",
        description: e.message,
        variant: "destructive",
      }),
  });

  const retry = useMutation({
    mutationFn: (id: number) =>
      api(`/sync-targets/${id}/retry`, { method: "POST" }),
    onSuccess: () => {
      toast({ title: "Erneuter Versuch eingereiht", variant: "success" });
      qc.invalidateQueries({ queryKey: ["sync-targets"] });
    },
  });

  const orgLabel = useMemo(() => {
    if (!orgs || !orgId) return "alle Firmen";
    return orgs.find((o) => o.id === orgId)?.name ?? "Firma";
  }, [orgs, orgId]);

  return (
    <div className="p-4 sm:p-6 space-y-4">
      <header className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            Sync-Inspector
          </h1>
          <p className="text-sm text-muted-foreground">
            Jede ausgehende Connector-Anfrage — was wir senden würden (Dry-Run)
            oder gesendet haben (Live). Aktiv: {orgLabel}.
          </p>
        </div>
      </header>

      <Card className="p-3 flex flex-wrap items-end gap-3">
        <FilterSelect
          label="Connector"
          value={connectorFilter ? String(connectorFilter) : ""}
          onChange={(v) => setConnectorFilter(v ? parseInt(v) : "")}
          options={[
            { value: "", label: "Alle" },
            ...(connectors ?? []).map((c) => ({
              value: String(c.id),
              label: `${c.name} (${c.type})`,
            })),
          ]}
        />
        <FilterSelect
          label="Modus"
          value={modeFilter}
          onChange={(v) => setModeFilter(v as ConnectorMode | "")}
          options={[
            { value: "", label: "Alle" },
            { value: "live", label: "Live" },
            { value: "dry_run", label: "Dry-Run" },
            { value: "off", label: "Aus" },
          ]}
        />
        <FilterSelect
          label="Status"
          value={statusFilter}
          onChange={(v) => setStatusFilter(v as SyncStatus | "")}
          options={[
            { value: "", label: "Alle" },
            { value: "pending", label: "Wartet" },
            { value: "synced", label: "Synchronisiert" },
            { value: "dry_run_ok", label: "Dry-Run OK" },
            { value: "failed", label: "Fehlgeschlagen" },
            { value: "skipped", label: "Übersprungen" },
          ]}
        />
        <Button
          variant="ghost"
          size="sm"
          onClick={() => list.refetch()}
          className="ml-auto"
        >
          <RefreshCcw className="h-3.5 w-3.5 mr-1" /> Aktualisieren
        </Button>
      </Card>

      <Card>
        <div className="divide-y divide-border">
          <div className="grid grid-cols-12 gap-2 px-4 py-2 text-xs uppercase tracking-wide text-muted-foreground font-medium">
            <div className="col-span-3">Beleg</div>
            <div className="col-span-2">Connector</div>
            <div className="col-span-1">Modus</div>
            <div className="col-span-2">Status</div>
            <div className="col-span-2">Wann</div>
            <div className="col-span-2 text-right">Aktion</div>
          </div>
          {(list.data?.items ?? []).map((st) => (
            <Row
              key={st.id}
              st={st}
              onOpen={() => setOpenId(st.id)}
              onPromote={() => promote.mutate(st.id)}
              onRetry={() => retry.mutate(st.id)}
            />
          ))}
          {list.isLoading && (
            <div className="p-6 text-center text-muted-foreground">
              Lade Sync-Logs…
            </div>
          )}
          {!list.isLoading && !list.data?.items.length && (
            <div className="p-6 text-center text-muted-foreground">
              Keine Sync-Einträge — entweder ist noch nichts gelaufen oder die
              Filter sind zu restriktiv.
            </div>
          )}
        </div>
      </Card>

      {openId !== null && (
        <DetailDrawer
          id={openId}
          onClose={() => setOpenId(null)}
          onPromote={() => {
            promote.mutate(openId);
            setOpenId(null);
          }}
          onRetry={() => {
            retry.mutate(openId);
            setOpenId(null);
          }}
        />
      )}
    </div>
  );
}

function FilterSelect({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <div className="min-w-[10rem]">
      <Label className="text-xs">{label}</Label>
      <Select
        value={value || "__all__"}
        onValueChange={(v) => onChange(v === "__all__" ? "" : v)}
      >
        <SelectTrigger>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {options.map((o) => (
            <SelectItem key={o.value || "__all__"} value={o.value || "__all__"}>
              {o.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

function Row({
  st,
  onOpen,
  onPromote,
  onRetry,
}: {
  st: SyncTargetRow;
  onOpen: () => void;
  onPromote: () => void;
  onRetry: () => void;
}) {
  const canPromote = st.status === "dry_run_ok" || st.mode === "dry_run";
  return (
    <div
      className="grid grid-cols-12 gap-2 items-center px-4 py-2 hover:bg-accent/30 cursor-pointer"
      onClick={onOpen}
    >
      <div className="col-span-3 min-w-0">
        <div className="font-medium truncate">
          {st.receipt?.provider ?? "—"}
        </div>
        <div className="text-xs text-muted-foreground truncate">
          {st.receipt?.filename ?? "—"} · {st.receipt?.amount ?? "—"}{" "}
          {st.receipt?.currency ?? ""}
        </div>
      </div>
      <div className="col-span-2 truncate">
        <span className="font-medium">{st.connector_name ?? "?"}</span>
        <span className="text-xs text-muted-foreground ml-1">
          ({st.connector_type})
        </span>
      </div>
      <div className="col-span-1">
        {st.mode ? (
          <Badge variant="outline" className={MODE_CLS[st.mode]}>
            {st.mode === "live"
              ? "Live"
              : st.mode === "dry_run"
              ? "Dry-Run"
              : "Aus"}
          </Badge>
        ) : (
          <span className="text-muted-foreground text-xs">—</span>
        )}
      </div>
      <div className="col-span-2">
        <Badge variant="outline" className={STATUS_CLS[st.status]}>
          {STATUS_LABEL[st.status]}
        </Badge>
        {st.error && (
          <div className="text-xs text-rose-500 truncate" title={st.error}>
            {st.error}
          </div>
        )}
      </div>
      <div className="col-span-2 text-xs text-muted-foreground">
        {formatDate(st.synced_at ?? st.updated_at ?? st.created_at)}
        {st.retry_count > 0 && <div>Versuche: {st.retry_count}</div>}
      </div>
      <div
        className="col-span-2 flex justify-end gap-1"
        onClick={(e) => e.stopPropagation()}
      >
        {canPromote && (
          <Button
            size="sm"
            variant="outline"
            onClick={onPromote}
            title="In Live-Modus erneut ausführen"
          >
            <PlayCircle className="h-3.5 w-3.5 mr-1" /> Live
          </Button>
        )}
        {st.status === "failed" && (
          <Button size="sm" variant="outline" onClick={onRetry}>
            <RefreshCcw className="h-3.5 w-3.5 mr-1" /> Retry
          </Button>
        )}
        <Button size="icon" variant="ghost" onClick={onOpen}>
          <ChevronRight className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}

function DetailDrawer({
  id,
  onClose,
  onPromote,
  onRetry,
}: {
  id: number;
  onClose: () => void;
  onPromote: () => void;
  onRetry: () => void;
}) {
  const { data, isLoading } = useQuery<SyncTargetDetail>({
    queryKey: ["sync-target", id],
    queryFn: () => api(`/sync-targets/${id}`),
  });

  const copyJson = (obj: any) => {
    navigator.clipboard.writeText(JSON.stringify(obj, null, 2));
    toast({ title: "In Zwischenablage kopiert", variant: "success" });
  };

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-4xl">
        <DialogHeader>
          <DialogTitle>
            Sync-Detail · #{id}
            {data && (
              <span className="ml-2 text-sm font-normal text-muted-foreground">
                {data.connector_name} ({data.connector_type})
              </span>
            )}
          </DialogTitle>
        </DialogHeader>
        {isLoading && (
          <div className="p-8 text-muted-foreground">Lade…</div>
        )}
        {data && (
          <div className="space-y-4 text-sm">
            <div className="grid grid-cols-3 gap-3">
              <div>
                <Label className="text-xs">Status</Label>
                <Badge variant="outline" className={STATUS_CLS[data.status]}>
                  {STATUS_LABEL[data.status]}
                </Badge>
              </div>
              <div>
                <Label className="text-xs">Modus</Label>
                <div>
                  {data.mode ? (
                    <Badge variant="outline" className={MODE_CLS[data.mode]}>
                      {data.mode}
                    </Badge>
                  ) : (
                    "—"
                  )}
                </div>
              </div>
              <div>
                <Label className="text-xs">HTTP</Label>
                <div>{data.response_status_code ?? "—"}</div>
              </div>
              <div>
                <Label className="text-xs">Beleg</Label>
                <div className="truncate">{data.receipt?.filename ?? "—"}</div>
              </div>
              <div>
                <Label className="text-xs">Lieferant</Label>
                <div>{data.receipt?.provider ?? "—"}</div>
              </div>
              <div>
                <Label className="text-xs">Betrag</Label>
                <div>
                  {data.receipt?.amount ?? "—"} {data.receipt?.currency ?? ""}
                </div>
              </div>
              <div>
                <Label className="text-xs">Externe ID</Label>
                <div className="flex items-center gap-1">
                  <span className="font-mono">
                    {data.external_id ?? "—"}
                  </span>
                  {data.external_id && data.connector_type === "bexio" && (
                    <a
                      href={`https://office.bexio.com/index.php/kb_bill/show/id/${data.external_id}`}
                      target="_blank"
                      rel="noreferrer"
                      className="text-muted-foreground hover:text-foreground"
                    >
                      <ExternalLink className="h-3.5 w-3.5" />
                    </a>
                  )}
                </div>
              </div>
              <div>
                <Label className="text-xs">Zeit</Label>
                <div>
                  {formatDate(
                    data.synced_at ?? data.updated_at ?? data.created_at,
                  )}
                </div>
              </div>
              <div>
                <Label className="text-xs">Retry</Label>
                <div>{data.retry_count}</div>
              </div>
            </div>

            {data.error && (
              <div className="rounded-md bg-rose-500/10 text-rose-700 dark:text-rose-300 text-xs px-3 py-2">
                {data.error}
              </div>
            )}

            <PayloadBlock
              title="Anfrage (request_payload)"
              payload={data.request_payload}
              onCopy={() => copyJson(data.request_payload)}
            />
            <PayloadBlock
              title="Antwort (response_payload)"
              payload={data.response_payload}
              onCopy={() => copyJson(data.response_payload)}
            />

            <div className="flex justify-end gap-2 pt-2">
              {(data.status === "dry_run_ok" || data.mode === "dry_run") && (
                <Button onClick={onPromote}>
                  <PlayCircle className="h-4 w-4 mr-1" /> Als Live ausführen
                </Button>
              )}
              {data.status === "failed" && (
                <Button variant="outline" onClick={onRetry}>
                  <RefreshCcw className="h-4 w-4 mr-1" /> Erneut versuchen
                </Button>
              )}
              <Button variant="outline" onClick={onClose}>
                Schließen
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function PayloadBlock({
  title,
  payload,
  onCopy,
}: {
  title: string;
  payload: Record<string, any> | null;
  onCopy: () => void;
}) {
  if (!payload) {
    return (
      <div>
        <Label className="text-xs">{title}</Label>
        <div className="text-xs text-muted-foreground italic">
          (kein Inhalt)
        </div>
      </div>
    );
  }
  return (
    <div>
      <div className="flex items-center justify-between">
        <Label className="text-xs">{title}</Label>
        <Button
          variant="ghost"
          size="sm"
          className="text-xs h-7"
          onClick={onCopy}
        >
          <Copy className="h-3 w-3 mr-1" /> Kopieren
        </Button>
      </div>
      <pre className="mt-1 max-h-72 overflow-auto rounded-md border border-input bg-muted/40 p-3 text-xs font-mono whitespace-pre-wrap">
        {JSON.stringify(payload, null, 2)}
      </pre>
    </div>
  );
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleString("de-CH", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}
