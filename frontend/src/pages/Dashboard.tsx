import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import { fmtMoney } from "../lib/format";
import { Bar, BarChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis, Line, LineChart } from "recharts";
import type { DashboardKPIs, DashboardCharts, PaymentMethod } from "../types";
import { PAYMENT_METHOD_LABEL } from "../types";
import { useUi } from "../store/ui";

export default function Dashboard() {
  const orgId = useUi((s) => s.selectedOrgId);

  const { data: kpis } = useQuery<DashboardKPIs>({
    queryKey: ["kpis", orgId],
    queryFn: () => api("/dashboard/kpis", { query: { organization_id: orgId ?? undefined } }),
  });

  const { data: charts } = useQuery<DashboardCharts>({
    queryKey: ["charts", orgId],
    queryFn: () => api("/dashboard/charts", { query: { organization_id: orgId ?? undefined, days: 90 } }),
  });

  const layerColors = { "1": "#22c55e", "2": "#6366f1", "3": "#f59e0b", "manual": "#94a3b8" } as Record<string, string>;
  const layerData = Object.entries(kpis?.layer_distribution ?? {}).map(([k, v]) => ({ name: layerLabel(k), value: v, color: layerColors[k] ?? "#94a3b8" }));

  return (
    <div className="p-4 sm:p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Übersicht</h1>
        <p className="text-sm text-muted-foreground">Überblick über Belegerfassung und Klassifizierung.</p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Kpi title="Belege (dieser Monat)" value={String(kpis?.receipts_this_month ?? "—")} sub={`${kpis?.receipts_last_month ?? 0} im Vormonat`} />
        <Kpi title="Betrag (dieser Monat)" value={fmtMoney(kpis?.total_amount_this_month, "CHF")} sub="nur verbuchte Belege" />
        <Kpi title="In Prüfung" value={String(kpis?.review_queue_size ?? "—")} sub={(kpis?.review_queue_size ?? 0) > 0 ? "Aufmerksamkeit nötig" : "alles erledigt"} />
        <Kpi title="Sync-Fehler" value={String(kpis?.sync_failed_count ?? "—")} sub="automatischer Retry" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Belege pro Tag</CardTitle>
            <CardDescription>Letzte 90 Tage</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={charts?.by_day ?? []}>
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                  <XAxis dataKey="bucket" tickLine={false} axisLine={false} tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }} />
                  <YAxis tickLine={false} axisLine={false} tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }} allowDecimals={false} />
                  <Tooltip contentStyle={{ background: "hsl(var(--popover))", border: "1px solid hsl(var(--border))", borderRadius: 8 }} />
                  <Line type="monotone" dataKey="value" stroke="#6366f1" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Klassifizierungs-Mix</CardTitle>
            <CardDescription>Beitrag der Klassifizierungs-Layer</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={layerData} dataKey="value" nameKey="name" innerRadius={45} outerRadius={75} paddingAngle={2}>
                    {layerData.map((entry) => <Cell key={entry.name} fill={entry.color} />)}
                  </Pie>
                  <Tooltip contentStyle={{ background: "hsl(var(--popover))", border: "1px solid hsl(var(--border))", borderRadius: 8 }} />
                </PieChart>
              </ResponsiveContainer>
            </div>
            <div className="grid grid-cols-2 gap-2 text-xs">
              {layerData.map((d) => (
                <div key={d.name} className="flex items-center gap-2">
                  <span className="h-2 w-2 rounded-full" style={{ background: d.color }} />
                  <span className="text-muted-foreground flex-1">{d.name}</span>
                  <span>{d.value}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Top Anbieter</CardTitle>
            <CardDescription>Nach Anzahl, letzte 90 Tage</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={charts?.top_providers ?? []}>
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                  <XAxis dataKey="provider" tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }} interval={0} angle={-15} textAnchor="end" height={60} />
                  <YAxis tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }} allowDecimals={false} />
                  <Tooltip contentStyle={{ background: "hsl(var(--popover))", border: "1px solid hsl(var(--border))", borderRadius: 8 }} />
                  <Bar dataKey="count" fill="#6366f1" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Zahlungsmethoden</CardTitle>
            <CardDescription>Ausgaben nach Methode, letzte 90 Tage</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={(charts?.by_payment_method ?? []).map((p) => ({
                      name: p.payment_method, value: Number(p.total_amount) || p.count,
                    }))}
                    dataKey="value" nameKey="name" innerRadius={45} outerRadius={85} paddingAngle={2}
                  >
                    {(charts?.by_payment_method ?? []).map((p, idx) => (
                      <Cell key={p.payment_method} fill={["#6366f1", "#22c55e", "#f59e0b", "#94a3b8", "#ef4444", "#06b6d4", "#a78bfa"][idx % 7]} />
                    ))}
                  </Pie>
                  <Tooltip contentStyle={{ background: "hsl(var(--popover))", border: "1px solid hsl(var(--border))", borderRadius: 8 }} />
                </PieChart>
              </ResponsiveContainer>
            </div>
            <div className="grid grid-cols-2 gap-1.5 text-xs mt-2">
              {(charts?.by_payment_method ?? []).map((p, idx) => (
                <div key={p.payment_method} className="flex items-center gap-2">
                  <span className="h-2 w-2 rounded-full" style={{ background: ["#6366f1", "#22c55e", "#f59e0b", "#94a3b8", "#ef4444", "#06b6d4", "#a78bfa"][idx % 7] }} />
                  <span className="text-muted-foreground flex-1">{PAYMENT_METHOD_LABEL[p.payment_method as PaymentMethod] ?? p.payment_method}</span>
                  <span>{p.count}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function Kpi({ title, value, sub }: { title: string; value: string; sub?: string }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardDescription className="text-xs">{title}</CardDescription>
        <CardTitle className="text-xl sm:text-2xl font-semibold truncate" title={value}>{value}</CardTitle>
      </CardHeader>
      {sub && <CardContent className="pt-0"><p className="text-xs text-muted-foreground">{sub}</p></CardContent>}
    </Card>
  );
}

function layerLabel(k: string) {
  switch (k) {
    case "1": return "Layer 1 (Regeln)";
    case "2": return "Layer 2 (KI)";
    case "3": return "Layer 3 (Prüfung)";
    case "manual": return "Manuell";
    default: return k;
  }
}
