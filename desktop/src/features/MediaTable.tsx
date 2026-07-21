import { AlertCircle, ArrowDown, ArrowUp } from "lucide-react";
import { useMemo } from "react";

import { Thumbnail } from "@/components/Thumbnail";
import { useAppStore, type SortKey } from "@/stores/appStore";
import type { ScanFileEntry } from "@/types";

const COLUMNS: Array<{ key: SortKey; label: string; className?: string }> = [
  { key: "original_name", label: "Original name" },
  { key: "suggested_name", label: "Suggested name" },
  { key: "category", label: "Category", className: "w-32" },
  { key: "media_type", label: "Type", className: "w-20" },
  { key: "status", label: "Status", className: "w-24" },
];

function StatusBadge({ status }: { status: ScanFileEntry["status"] }) {
  const styles: Record<string, string> = {
    success: "bg-emerald-100 text-emerald-800",
    failed: "bg-red-100 text-red-800",
    skipped: "bg-amber-100 text-amber-800",
  };
  return (
    <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${styles[status]}`}>
      {status}
    </span>
  );
}

export function MediaTable() {
  const report = useAppStore((s) => s.report);
  const selectedPath = useAppStore((s) => s.selectedPath);
  const select = useAppStore((s) => s.select);
  const setSuggestedName = useAppStore((s) => s.setSuggestedName);
  const setRenameEnabled = useAppStore((s) => s.setRenameEnabled);
  const setSort = useAppStore((s) => s.setSort);
  const sortKey = useAppStore((s) => s.sortKey);
  const sortAsc = useAppStore((s) => s.sortAsc);
  const visibleEntries = useAppStore((s) => s.visibleEntries);
  const entryErrors = useAppStore((s) => s.entryErrors);
  // visibleEntries/entryErrors are stable selectors, so the filter inputs
  // must be subscribed to explicitly for the table to re-render.
  const filter = useAppStore((s) => s.filter);
  const search = useAppStore((s) => s.search);
  const categoryFilter = useAppStore((s) => s.categoryFilter);

  const rows = useMemo(
    () => visibleEntries(),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [visibleEntries, report, filter, search, categoryFilter, sortKey, sortAsc],
  );
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const errors = useMemo(() => entryErrors(), [entryErrors, report]);

  if (!report) return null;

  if (rows.length === 0) {
    return (
      <div className="panel flex flex-1 items-center justify-center p-8 text-sm text-slate-500">
        No files match the current filters.
      </div>
    );
  }

  return (
    <div className="panel flex-1 overflow-auto">
      <table className="w-full border-collapse text-sm">
        <caption className="sr-only">
          Analyzed media files and their suggested names
        </caption>
        <thead className="sticky top-0 z-10 bg-slate-50 text-left">
          <tr className="border-b border-slate-200">
            <th scope="col" className="w-10 px-2 py-2">
              <span className="sr-only">Rename enabled</span>
            </th>
            <th scope="col" className="w-14 px-2 py-2">
              <span className="sr-only">Preview</span>
            </th>
            {COLUMNS.map((column) => (
              <th
                key={column.key}
                scope="col"
                className={`px-2 py-2 font-medium ${column.className ?? ""}`}
              >
                <button
                  type="button"
                  className="inline-flex items-center gap-1 hover:text-blue-700"
                  onClick={() => setSort(column.key)}
                  aria-label={`Sort by ${column.label}`}
                >
                  {column.label}
                  {sortKey === column.key ? (
                    sortAsc ? (
                      <ArrowUp className="h-3 w-3" aria-hidden />
                    ) : (
                      <ArrowDown className="h-3 w-3" aria-hidden />
                    )
                  ) : null}
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((entry) => {
            const problem = errors.get(entry.original_path);
            const isSelected = entry.original_path === selectedPath;
            const editable = entry.status === "success";
            return (
              <tr
                key={entry.original_path}
                onClick={() => select(entry.original_path)}
                className={`cursor-pointer border-b border-slate-100 ${
                  isSelected ? "bg-blue-50" : "hover:bg-slate-50"
                }`}
              >
                <td className="px-2 py-1.5">
                  <input
                    type="checkbox"
                    className="h-4 w-4"
                    checked={entry.rename_enabled && editable}
                    disabled={!editable}
                    aria-label={`Rename ${entry.original_name}`}
                    onClick={(event) => event.stopPropagation()}
                    onChange={(event) =>
                      setRenameEnabled(entry.original_path, event.target.checked)
                    }
                  />
                </td>
                <td className="px-2 py-1.5">
                  <Thumbnail entry={entry} size={36} />
                </td>
                <td className="max-w-[16rem] truncate px-2 py-1.5" title={entry.original_name}>
                  {entry.original_name}
                </td>
                <td className="px-2 py-1.5">
                  {editable ? (
                    <div>
                      <input
                        type="text"
                        value={entry.suggested_name ?? ""}
                        aria-label={`Suggested name for ${entry.original_name}`}
                        aria-invalid={problem ? true : undefined}
                        onClick={(event) => event.stopPropagation()}
                        onChange={(event) =>
                          setSuggestedName(entry.original_path, event.target.value)
                        }
                        className={`w-full rounded border px-1.5 py-0.5 text-sm ${
                          problem
                            ? "border-red-500 bg-red-50"
                            : "border-transparent bg-transparent hover:border-slate-300 focus:border-blue-500 focus:bg-white"
                        }`}
                      />
                      {problem ? (
                        <p className="mt-0.5 flex items-center gap-1 text-xs text-red-700">
                          <AlertCircle className="h-3 w-3 shrink-0" aria-hidden />
                          {problem}
                        </p>
                      ) : null}
                    </div>
                  ) : (
                    <span className="text-slate-400">—</span>
                  )}
                </td>
                <td className="px-2 py-1.5">
                  {entry.classification?.category ?? "—"}
                </td>
                <td className="px-2 py-1.5">{entry.media_type}</td>
                <td className="px-2 py-1.5">
                  <StatusBadge status={entry.status} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
