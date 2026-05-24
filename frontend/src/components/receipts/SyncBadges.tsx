import { Link } from "react-router-dom";
import {
  CheckCircle2,
  CircleDashed,
  Eye,
  Pause,
  XCircle,
} from "lucide-react";
import type { Connector, SyncTarget } from "../../types";
import { cn } from "../../lib/utils";

const STATUS_VISUAL: Record<
  SyncTarget["status"],
  { icon: typeof CheckCircle2; cls: string; label: string }
> = {
  synced: {
    icon: CheckCircle2,
    cls: "text-emerald-600 dark:text-emerald-400",
    label: "Synchronisiert",
  },
  dry_run_ok: {
    icon: Eye,
    cls: "text-yellow-600 dark:text-yellow-400",
    label: "Dry-Run OK",
  },
  failed: {
    icon: XCircle,
    cls: "text-rose-600 dark:text-rose-400",
    label: "Fehlgeschlagen",
  },
  pending: {
    icon: CircleDashed,
    cls: "text-muted-foreground",
    label: "Wartet",
  },
  skipped: {
    icon: Pause,
    cls: "text-muted-foreground",
    label: "Übersprungen",
  },
};

const TYPE_LABEL: Record<string, string> = {
  bexio: "Bexio",
  onedrive: "OneDrive",
  local: "Lokal",
};

/**
 * Compact icon row showing the sync state for each connector on a receipt.
 * Used in inbox rows — tiny by design.
 */
export function SyncRowIcons({
  targets,
  connectors,
}: {
  targets: SyncTarget[];
  connectors: Connector[] | undefined;
}) {
  if (!targets.length) {
    return <span className="text-muted-foreground text-xs">—</span>;
  }
  return (
    <div className="flex items-center gap-1">
      {targets.map((t) => {
        const visual = STATUS_VISUAL[t.status];
        const conn = connectors?.find((c) => c.id === t.connector_id);
        const type = conn?.type ?? "?";
        const Icon = visual.icon;
        const title =
          `${TYPE_LABEL[type] ?? type}: ${visual.label}` +
          (t.mode ? ` (${t.mode})` : "") +
          (t.error ? `\n${t.error}` : "");
        return (
          <Link
            key={t.id}
            to={`/settings/sync-inspector?receipt_id=${t.receipt_id}`}
            title={title}
            className={cn(
              "inline-flex items-center gap-0.5 rounded px-1 py-0.5 hover:bg-accent",
              visual.cls,
            )}
            onClick={(e) => e.stopPropagation()}
          >
            <Icon className="h-3.5 w-3.5" />
            <span className="text-[10px] uppercase">
              {TYPE_LABEL[type]?.[0] ?? "?"}
            </span>
          </Link>
        );
      })}
    </div>
  );
}

/**
 * Full row with mode + status + timestamp + connector name.
 * Used in the receipt detail panel.
 */
export function SyncDetailRow({
  target,
  connector,
}: {
  target: SyncTarget;
  connector: Connector | undefined;
}) {
  const visual = STATUS_VISUAL[target.status];
  const Icon = visual.icon;
  const synced = target.synced_at
    ? new Date(target.synced_at).toLocaleString("de-CH", {
        dateStyle: "short",
        timeStyle: "short",
      })
    : null;
  const modeCls =
    target.mode === "live"
      ? "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border-emerald-500/30"
      : target.mode === "dry_run"
      ? "bg-yellow-500/15 text-yellow-700 dark:text-yellow-300 border-yellow-500/30"
      : "bg-muted text-muted-foreground border-muted";

  return (
    <div className="rounded-md border border-border px-3 py-2 text-sm">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <Icon className={cn("h-4 w-4 shrink-0", visual.cls)} />
          <div className="truncate">
            <span className="font-medium">
              {connector?.name ?? `Connector #${target.connector_id}`}
            </span>
            <span className="text-xs text-muted-foreground ml-1">
              {connector?.type ? `(${TYPE_LABEL[connector.type] ?? connector.type})` : ""}
            </span>
          </div>
        </div>
        <div className="flex items-center gap-1.5">
          {target.mode && (
            <span
              className={cn(
                "rounded border px-1.5 py-0.5 text-[10px] uppercase tracking-wider",
                modeCls,
              )}
            >
              {target.mode === "live"
                ? "Live"
                : target.mode === "dry_run"
                ? "Dry-Run"
                : "Aus"}
            </span>
          )}
          <span className={cn("text-xs", visual.cls)}>{visual.label}</span>
        </div>
      </div>
      <div className="flex items-center justify-between mt-1 text-xs text-muted-foreground">
        <div>
          {synced ? `Gesynct ${synced}` : "—"}
          {target.retry_count > 0 && (
            <span className="ml-2">Versuche: {target.retry_count}</span>
          )}
        </div>
        <Link
          to={`/settings/sync-inspector?receipt_id=${target.receipt_id}`}
          className="hover:text-foreground"
          onClick={(e) => e.stopPropagation()}
        >
          Im Inspector öffnen →
        </Link>
      </div>
      {target.error && (
        <div className="mt-1 text-xs text-rose-500 break-words">
          {target.error}
        </div>
      )}
      {target.external_id && connector?.type === "bexio" && (
        <a
          href={`https://office.bexio.com/index.php/kb_bill/show/id/${target.external_id}`}
          target="_blank"
          rel="noreferrer"
          className="mt-1 inline-block text-xs text-blue-600 dark:text-blue-400 hover:underline"
          onClick={(e) => e.stopPropagation()}
        >
          In Bexio öffnen ↗ (#{target.external_id})
        </a>
      )}
    </div>
  );
}
