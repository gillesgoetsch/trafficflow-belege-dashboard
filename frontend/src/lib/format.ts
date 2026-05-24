import { format, formatDistanceToNowStrict, parseISO } from "date-fns";
import { de } from "date-fns/locale";

export function fmtDate(input?: string | Date | null): string {
  if (!input) return "—";
  const d = typeof input === "string" ? parseISO(input) : input;
  return format(d, "yyyy-MM-dd");
}

export function fmtDateTime(input?: string | Date | null): string {
  if (!input) return "—";
  const d = typeof input === "string" ? parseISO(input) : input;
  return format(d, "yyyy-MM-dd HH:mm");
}

export function fmtRelative(input?: string | Date | null): string {
  if (!input) return "—";
  const d = typeof input === "string" ? parseISO(input) : input;
  return formatDistanceToNowStrict(d, { addSuffix: true, locale: de });
}

export function fmtMoney(amount?: number | string | null, currency?: string | null): string {
  if (amount === null || amount === undefined || amount === "") return "—";
  const n = typeof amount === "number" ? amount : parseFloat(amount as string);
  if (Number.isNaN(n)) return "—";
  try {
    return new Intl.NumberFormat("de-CH", {
      style: "currency",
      currency: currency || "CHF",
      maximumFractionDigits: 2,
    }).format(n);
  } catch {
    return `${n.toFixed(2)} ${currency || ""}`.trim();
  }
}
