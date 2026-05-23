import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import { fmtMoney } from "../lib/format";
import { Bar, BarChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis, Line, LineChart } from "recharts";
import type { DashboardKPIs, DashboardCharts } from "../types";
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
        <h1 className="text-2xl font-semibold tracking-tight">Dashboard</h1>
        <p className="text-sm text-muted-foreground">Overview of receipt ingestion and classification.</p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Kpi title="Receipts (this month)" value={String(kpis?.receipts_this_month ?? "—")} sub={`${kpis?.receipts_last_month ?? 0} last month`} />
        <Kpi title="Amount (this month)" value={fmtMoney(kpis?.total_amount_this_month, "CHF")} sub="processed only" />
        <Kpi title="Review queue" value={String(kpis?.review_queue_size ?? "—")} sub={(kpis?.review_queue_size ?? 0) > 0 ? "needs attention" : "all clear"} />
        <Kpi title="Sync failures" value={String(kpis?.sync_failed_count ?? "—")} sub="retried automatically" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Receipts per day</CardTitle>
            <CardDescription>Last 90 days</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={charts?.by_day ?? []}>
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                  <XAxis dataKey="bucket" tickLine={false} axisLine={false} tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }} />
                  <YAxis tickLine={false} axisLine={false} tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }} allowDecimals={false} />
                  <Tooltip contentStyle={{ background: "hsl(var(--popover))", border: "1px solid hsl(var(--border))", borderRadius: 8 }} />
                  <Line type="monotone" dataKey="value" stroke="hsl(var(--primary))" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Classification mix</CardTitle>
            <CardDescription>How each layer contributes</CardDescription>
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

      <Card>
        <CardHeader>
          <CardTitle>Top providers</CardTitle>
          <CardDescription>By count, last 90 days</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={charts?.top_providers ?? []}>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                <XAxis dataKey="provider" tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }} />
                <YAxis tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }} allowDecimals={false} />
                <Tooltip contentStyle={{ background: "hsl(var(--popover))", border: "1px solid hsl(var(--border))", borderRadius: 8 }} />
                <Bar dataKey="count" fill="hsl(var(--primary))" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function Kpi({ title, value, sub }: { title: string; value: string; sub?: string }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardDescription className="text-xs">{title}</CardDescription>
        <CardTitle className="text-2xl font-semibold">{value}</CardTitle>
      </CardHeader>
      {sub && <CardContent className="pt-0"><p className="text-xs text-muted-foreground">{sub}</p></CardContent>}
    </Card>
  );
}

function layerLabel(k: string) {
  switch (k) {
    case "1": return "Layer 1 (rules)";
    case "2": return "Layer 2 (LLM)";
    case "3": return "Layer 3 (review)";
    case "manual": return "Manual";
    default: return k;
  }
}
