"use client";
import { useState } from "react";
import { Shield, Trash2, UserCheck, UserX } from "lucide-react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { fmtBytes, timeAgo } from "@/lib/utils";
import { useAuth } from "@/components/auth";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { EmptyState, ErrorNote, PageHeader, Skeleton } from "@/components/ui/misc";

export default function Admin() {
  const { user } = useAuth();
  const { data: users, reload, error } = useApi<any[]>(user?.is_admin ? "/admin/users" : null);
  const { data: stats } = useApi<any>(user?.is_admin ? "/admin/stats" : null);
  const [del, setDel] = useState<any | null>(null);
  const [err, setErr] = useState<string | null>(null);
  if (!user?.is_admin) return <EmptyState icon={Shield} title="Administrator access required" description="Ask an administrator to grant you access." />;
  const patch = async (u: any, body: any) => { setErr(null); try { await api(`/admin/users/${u.id}`, { method: "PATCH", json: body }); reload(); } catch (e: any) { setErr(e.message); } };
  const remove = async () => { try { await api(`/admin/users/${del.id}?confirm=true`, { method: "DELETE" }); setDel(null); reload(); } catch (e: any) { setErr(e.message); } };
  return (
    <div className="space-y-6 animate-in">
      <PageHeader title="Admin" description="Manage accounts and monitor usage. For privacy, administrators cannot open other users' datasets or results." />
      {(err || error) && <ErrorNote message={(err || error)!} />}
      {stats && <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        {[["Users", stats.users], ["Disabled", stats.disabled_users], ["Datasets", stats.datasets], ["Analyses", stats.analyses], ["Running now", stats.running], ["Storage", fmtBytes(stats.storage_bytes)]].map(([k, v]) => (
          <Card key={k as string} className="p-3.5"><div className="text-[12px] text-fg-3">{k}</div><div className="mt-1 text-xl font-semibold num">{v}</div></Card>))}
      </div>}
      {stats && <div className="flex flex-wrap gap-2 text-[12.5px]"><Badge tone={stats.llm.configured ? "success" : "neutral"}>LLM: {stats.llm.configured ? `${stats.llm.provider} / ${stats.llm.model}` : "not configured"}</Badge><Badge tone={stats.sandbox_network_isolation ? "success" : "warning"}>Sandbox network namespace: {stats.sandbox_network_isolation ? "on" : "unavailable on this host"}</Badge><Badge tone="outline">{stats.failed} failed analyses</Badge></div>}
      {!users ? <Skeleton className="h-64" /> : (
        <div className="overflow-auto rounded-xl border border-border bg-surface">
          <table className="w-full text-[13px]">
            <thead className="bg-surface-2 text-left text-fg-2"><tr>{["User", "Role", "Datasets", "Analyses", "Experiments", "Lessons", "Storage", "Sessions", "Joined", ""].map((h) => <th key={h} className="px-3 py-2.5 font-medium whitespace-nowrap">{h}</th>)}</tr></thead>
            <tbody>{users.map((u) => (
              <tr key={u.id} className="border-t border-border">
                <td className="px-3 py-2.5"><div className="font-medium text-fg">{u.name}</div><div className="text-[12px] text-fg-3">{u.email}</div></td>
                <td className="px-3 py-2.5">{u.is_admin ? <Badge tone="accent">Admin</Badge> : <Badge tone="outline">User</Badge>}{u.disabled && <Badge tone="danger" className="ml-1">Disabled</Badge>}</td>
                {[u.datasets, u.analyses, u.experiments, u.lessons].map((v, i) => <td key={i} className="px-3 py-2.5 num">{v}</td>)}
                <td className="px-3 py-2.5 num">{fmtBytes(u.storage_bytes)}</td><td className="px-3 py-2.5 num">{u.active_sessions}</td><td className="px-3 py-2.5 text-fg-3 whitespace-nowrap">{timeAgo(u.created_at)}</td>
                <td className="px-3 py-2.5 whitespace-nowrap">{u.id !== user.id && <div className="flex gap-1">
                  <Button size="sm" variant="ghost" onClick={() => patch(u, { disabled: !u.disabled })}>{u.disabled ? <><UserCheck /> Enable</> : <><UserX /> Disable</>}</Button>
                  <Button size="sm" variant="ghost" onClick={() => patch(u, { is_admin: !u.is_admin })}><Shield /> {u.is_admin ? "Revoke admin" : "Make admin"}</Button>
                  <Button size="sm" variant="ghost" onClick={() => setDel(u)} aria-label="Delete user"><Trash2 /></Button></div>}</td>
              </tr>))}</tbody>
          </table>
        </div>
      )}
      <Dialog open={!!del} onOpenChange={(o) => !o && setDel(null)}>
        <DialogContent title="Delete this account?" description="The account and all of its datasets, analyses, experiments and lessons are permanently deleted.">
          <div className="space-y-3 text-[13px]"><div className="rounded-lg bg-surface-2 p-3 font-medium">{del?.email}</div><div className="flex justify-end gap-2"><Button variant="ghost" onClick={() => setDel(null)}>Cancel</Button><Button variant="danger" onClick={remove}><Trash2 /> Delete account</Button></div></div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
