import { Search } from "lucide-react";
import { useMemo } from "react";

import { useAppStore, type StatusFilter } from "@/stores/appStore";

const FILTERS: Array<{ value: StatusFilter; label: string }> = [
  { value: "all", label: "All" },
  { value: "images", label: "Images" },
  { value: "videos", label: "Videos" },
  { value: "success", label: "Success" },
  { value: "failed", label: "Failed" },
  { value: "skipped", label: "Skipped" },
  { value: "enabled", label: "Enabled" },
  { value: "disabled", label: "Disabled" },
];

export function FilterBar() {
  const report = useAppStore((s) => s.report);
  const filter = useAppStore((s) => s.filter);
  const setFilter = useAppStore((s) => s.setFilter);
  const search = useAppStore((s) => s.search);
  const setSearch = useAppStore((s) => s.setSearch);
  const categoryFilter = useAppStore((s) => s.categoryFilter);
  const setCategoryFilter = useAppStore((s) => s.setCategoryFilter);
  const setVisibleEnabled = useAppStore((s) => s.setVisibleEnabled);
  const resetSuggestedNames = useAppStore((s) => s.resetSuggestedNames);

  const categories = useMemo(() => {
    const found = new Set<string>();
    for (const file of report?.files ?? []) {
      if (file.classification?.category) found.add(file.classification.category);
    }
    return [...found].sort();
  }, [report]);

  return (
    <div className="panel flex flex-wrap items-center gap-2 p-2">
      <div className="flex flex-wrap gap-1" role="group" aria-label="Filter files">
        {FILTERS.map((item) => (
          <button
            key={item.value}
            type="button"
            aria-pressed={filter === item.value}
            onClick={() => setFilter(item.value)}
            className={`rounded px-2 py-1 text-xs font-medium ${
              filter === item.value
                ? "bg-blue-600 text-white"
                : "bg-slate-100 text-slate-700 hover:bg-slate-200"
            }`}
          >
            {item.label}
          </button>
        ))}
      </div>

      <label className="flex items-center gap-1.5 text-sm">
        <span className="sr-only">Category</span>
        <select
          className="field"
          value={categoryFilter}
          onChange={(event) => setCategoryFilter(event.target.value)}
          aria-label="Filter by category"
        >
          <option value="all">All categories</option>
          {categories.map((category) => (
            <option key={category} value={category}>
              {category}
            </option>
          ))}
        </select>
      </label>

      <div className="relative min-w-[12rem] flex-1">
        <Search
          className="pointer-events-none absolute left-2 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400"
          aria-hidden
        />
        <input
          type="search"
          className="field w-full pl-8"
          placeholder="Search name, caption or category"
          aria-label="Search files"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
      </div>

      <button type="button" className="btn-secondary" onClick={() => setVisibleEnabled(true)}>
        Enable visible
      </button>
      <button type="button" className="btn-secondary" onClick={() => setVisibleEnabled(false)}>
        Disable visible
      </button>
      <button type="button" className="btn-secondary" onClick={resetSuggestedNames}>
        Reset names
      </button>
    </div>
  );
}
