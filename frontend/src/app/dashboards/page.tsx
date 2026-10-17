"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { BellRing, LayoutGrid, Plus } from "lucide-react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { fmtNum, timeAgo } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Label, Select } from "@/components/ui/input";
import { EmptyState, ErrorNote, PageHeader, Skeleton } from "@/components/ui/misc";

export default function DashboardsPage() {
  const router = useRouter();
  const boards = useApi<any[]>("/dashboards");
  const alerts = useApi<any[]>("/alerts");
  const datasets = useApi<any[]>("/datasets");
  const [name, setName] = useState("");
  const [ds, setDs] = useState("");
  const [err, setErr] = useState<string | null>(null);
  async function create() {
    setErr(null);
    try { const b = await api("/dashboards", { method: "POST", json: { name: name.trim(), dataset_id: ds } }); router.push(`/dashboards/${b.id}`); }
    catch (e: any) { setErr(e.message); }
  }
  return (
    <div className="space-y-6 animate-in">
      <PageHeader title="Dashboards" description="Boards of live tiles. Each tile re-runs its query on the latest version of the data, and KPI tiles can carry alert rules." />
      <Card className="p-4">
        <div className="grid items-end gap-3 md:grid-cols-[1fr_1fr_auto]">
          <div className="space-y-1.5"><Label>Name</Label><Input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Monthly sales" maxLength={200} /></div>
          <div className="space-y-1.5"><Label>Dataset</Label><Select value={ds} onChange={(e) => setDs(e.target.value)}><option value="">Select…</option>{datasets.data?.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</Select></div>
          <Button onClick={create} disabled={!name.trim() || !ds}><Plus /> Create dashboard</Button>
        </div>
        {err && <div className="mt-2"><ErrorNote message={err} /></div>}
        <p className="mt-2 text-[12px] text-fg-3">Add tiles from any answer in a dataset's Ask tab with “Add to dashboard”.</p>
      </Card>
      {alerts.data && alerts.data.length > 0 && (
        <Card>
          <CardHeader><div><CardTitle className="flex items-center gap-2"><BellRing className="size-4 text-warning" /> Alerts</CardTitle><CardDescription>Rule breaches recorded when a KPI was evaluated on a new data version.</CardDescription></div></CardHeader>
          <CardContent><ul className="space-y-1.5">{alerts.data.map((a) => (
            <li key={a.id} className="flex flex-wrap items-center gap-2 rounded-lg border border-warning/30 bg-warning-soft/40 px-3 py-2 text-[13px]">
              <Link href={`/dashboards/${a.dashboard_id}`} className="font-medium text-fg hover:text-accent-text">{a.dashboard}: {a.tile}</Link>
              <span className="num text-fg-2">value {fmtNum(a.value)}</span><span className="text-fg-2">{a.message}</span><span className="ml-auto text-[12px] text-fg-3">{timeAgo(a.created_at)}</span></li>))}</ul></CardContent>
        </Card>
      )}
      {boards.loading ? <Skeleton className="h-40" /> : !boards.data?.length ? <EmptyState icon={LayoutGrid} title="No dashboards yet" description="Create one above, then pin answers to it from the Ask tab." /> : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {boards.data.map((b) => (
            <Link key={b.id} href={`/dashboards/${b.id}`}><Card className="lift h-full p-4">
              <div className="text-[15px] font-semibold text-fg">{b.name}</div>
              <div className="mt-1 text-[12.5px] text-fg-3">{b.dataset_name} · {b.tiles.length} tiles · updated {timeAgo(b.updated_at)}</div>
            </Card></Link>
          ))}
        </div>
      )}
    </div>
  );
}
