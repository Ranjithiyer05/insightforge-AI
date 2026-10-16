"use client";
import { useState } from "react";
import { Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "./ui/button";
import { Dialog, DialogContent } from "./ui/dialog";
import { ErrorNote } from "./ui/misc";

export function DeleteDatasetDialog({ ds, onClose, onDeleted }: { ds: any | null; onClose: () => void; onDeleted: () => void }) {
  const [err, setErr] = useState<string | null>(null);
  const del = async () => {
    try { await api(`/datasets/${ds.id}?confirm=true`, { method: "DELETE" }); onDeleted(); onClose(); } catch (e: any) { setErr(e.message); }
  };
  return (
    <Dialog open={!!ds} onOpenChange={(o) => !o && onClose()}>
      <DialogContent title="Delete dataset?" description="This permanently deletes the stored file and every analysis that used it. Learned lessons keep only anonymous dataset fingerprints.">
        <div className="space-y-3 text-[13px]"><div className="rounded-lg bg-surface-2 p-3 font-medium">{ds?.name}</div>{err && <ErrorNote message={err} />}
          <div className="flex justify-end gap-2"><Button variant="ghost" onClick={onClose}>Cancel</Button><Button variant="danger" onClick={del}><Trash2 /> Delete permanently</Button></div></div>
      </DialogContent>
    </Dialog>
  );
}

