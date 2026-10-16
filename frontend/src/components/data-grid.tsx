"use client";
import { ColumnDef, flexRender, getCoreRowModel, getSortedRowModel, SortingState, useReactTable } from "@tanstack/react-table";
import { ArrowDown, ArrowUp } from "lucide-react";
import { useMemo, useState } from "react";
import { cn, fmtNum } from "@/lib/utils";

/** Accessible, sortable grid for dataset previews and result tables. */
export function DataGrid({ columns, rows, types, maxHeight = 420, dense }: { columns: string[]; rows: any[]; types?: Record<string, string>; maxHeight?: number; dense?: boolean }) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const data = useMemo(() => rows.map((r) => (Array.isArray(r) ? Object.fromEntries(columns.map((c, i) => [c, r[i]])) : r)), [rows, columns]);
  const defs = useMemo<ColumnDef<any>[]>(() => columns.map((c) => ({
    id: c, accessorFn: (r: any) => r[c], header: c,
    cell: (info) => {
      const v = info.getValue();
      if (v === null || v === undefined) return <span className="text-fg-3/70 italic">null</span>;
      return typeof v === "number" ? <span className="num">{fmtNum(v)}</span> : String(v);
    },
  })), [columns]);
  const table = useReactTable({ data, columns: defs, state: { sorting }, onSortingChange: setSorting, getCoreRowModel: getCoreRowModel(), getSortedRowModel: getSortedRowModel() });
  return (
    <div className="overflow-auto rounded-lg border border-border scrollbar-thin" style={{ maxHeight }}>
      <table className="w-full border-collapse text-[12.5px]">
        <thead className="sticky top-0 z-10 bg-surface-2">
          {table.getHeaderGroups().map((hg) => (
            <tr key={hg.id}>
              {hg.headers.map((h) => {
                const s = h.column.getIsSorted();
                return (
                  <th key={h.id} className="border-b border-border px-3 py-2 text-left font-medium text-fg-2 whitespace-nowrap">
                    <button className="inline-flex items-center gap-1 hover:text-fg" onClick={h.column.getToggleSortingHandler()}>
                      {flexRender(h.column.columnDef.header, h.getContext())}
                      {s === "asc" ? <ArrowUp className="size-3" /> : s === "desc" ? <ArrowDown className="size-3" /> : null}
                    </button>
                    {types?.[h.id] && <div className="text-[10.5px] font-normal text-fg-3">{types[h.id]}</div>}
                  </th>
                );
              })}
            </tr>
          ))}
        </thead>
        <tbody>
          {table.getRowModel().rows.map((r) => (
            <tr key={r.id} className="border-b border-border/70 last:border-0 hover:bg-surface-2/60">
              {r.getVisibleCells().map((c) => (
                <td key={c.id} className={cn("px-3 whitespace-nowrap text-fg max-w-[260px] truncate", dense ? "py-1" : "py-1.5", typeof c.getValue() === "number" && "text-right")}>
                  {flexRender(c.column.columnDef.cell, c.getContext())}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
