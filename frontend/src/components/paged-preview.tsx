"use client";
import { useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useApi } from "@/lib/hooks";
import { Button } from "./ui/button";
import { Skeleton } from "./ui/misc";
import { DataGrid } from "./data-grid";

/** Dataset preview fetched one page at a time from the server. */
export function PagedPreview({ datasetId, types, pageSize = 50, maxHeight = 460 }: { datasetId: string; types?: Record<string, string>; pageSize?: number; maxHeight?: number }) {
  const [page, setPage] = useState(0);
  const { data, loading } = useApi<any>(`/datasets/${datasetId}/preview?limit=${pageSize}&offset=${page * pageSize}`);
  const total = data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <div className="space-y-2">
      {data ? <DataGrid columns={data.columns} rows={data.rows} types={types} maxHeight={maxHeight} dense /> : <Skeleton className="h-64" />}
      <div className="flex items-center justify-between text-[12px] text-fg-3">
        <span className="num">{total ? `Rows ${(page * pageSize + 1).toLocaleString()}–${Math.min(total, (page + 1) * pageSize).toLocaleString()} of ${total.toLocaleString()}` : ""}</span>
        <div className="flex items-center gap-1">
          <Button size="icon-sm" variant="ghost" onClick={() => setPage(0)} disabled={page === 0 || loading} aria-label="First page"><ChevronLeft /><ChevronLeft className="-ml-3" /></Button>
          <Button size="icon-sm" variant="ghost" onClick={() => setPage((p) => Math.max(0, p - 1))} disabled={page === 0 || loading} aria-label="Previous page"><ChevronLeft /></Button>
          <span className="num px-1">Page {page + 1} of {pages.toLocaleString()}</span>
          <Button size="icon-sm" variant="ghost" onClick={() => setPage((p) => Math.min(pages - 1, p + 1))} disabled={page >= pages - 1 || loading} aria-label="Next page"><ChevronRight /></Button>
          <Button size="icon-sm" variant="ghost" onClick={() => setPage(pages - 1)} disabled={page >= pages - 1 || loading} aria-label="Last page"><ChevronRight /><ChevronRight className="-ml-3" /></Button>
        </div>
      </div>
    </div>
  );
}
