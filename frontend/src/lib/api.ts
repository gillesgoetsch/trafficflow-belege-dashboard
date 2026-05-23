// Thin fetch wrapper that:
//  - uses cookies (HttpOnly belege_session) for auth
//  - falls back to Bearer when localStorage has a token
//  - throws structured errors that components can display
const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "/api";

export class ApiError extends Error {
  status: number;
  body: any;
  constructor(status: number, message: string, body?: any) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

type FetchOpts = {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  body?: any;
  headers?: Record<string, string>;
  raw?: boolean;
  signal?: AbortSignal;
  query?: Record<string, string | number | boolean | undefined | null>;
};

function toQuery(params?: FetchOpts["query"]): string {
  if (!params) return "";
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    sp.set(k, String(v));
  }
  const qs = sp.toString();
  return qs ? `?${qs}` : "";
}

export async function api<T = any>(path: string, opts: FetchOpts = {}): Promise<T> {
  const headers: Record<string, string> = { ...(opts.headers ?? {}) };
  let body: BodyInit | undefined;

  if (opts.body !== undefined) {
    if (opts.body instanceof FormData) {
      body = opts.body;
    } else {
      body = JSON.stringify(opts.body);
      headers["Content-Type"] = "application/json";
    }
  }

  const token = localStorage.getItem("belege_token");
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const url = `${BASE}${path}${toQuery(opts.query)}`;
  const res = await fetch(url, {
    method: opts.method ?? "GET",
    headers,
    body,
    credentials: "include",
    signal: opts.signal,
  });
  if (opts.raw) return res as unknown as T;

  const text = await res.text();
  let parsed: any = undefined;
  try {
    parsed = text ? JSON.parse(text) : undefined;
  } catch {
    parsed = text;
  }

  if (!res.ok) {
    const detail = parsed?.detail ?? parsed?.message ?? `HTTP ${res.status}`;
    throw new ApiError(res.status, String(detail), parsed);
  }
  return parsed as T;
}

export const apiBase = BASE;
