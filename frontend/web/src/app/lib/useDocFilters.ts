import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router-dom";

/**
 * Documents-page filters, mirrored to the URL. Only `source` + `search` —
 * those are what the real `GET /api/documents` endpoint supports. (Region /
 * tag filtering needs the knowledge-map compile step, which isn't part of the
 * raw harvested document set.)
 */
export interface DocFilters {
  sources: string[];
  search: string;
}

export function useDocFilters(): {
  filters: DocFilters;
  setFilters: (next: Partial<DocFilters>) => void;
  clear: () => void;
  activeCount: number;
} {
  const [params, setParams] = useSearchParams();

  const filters = useMemo<DocFilters>(
    () => ({
      sources: params.get("source")?.split(",").filter(Boolean) ?? [],
      search: params.get("q") ?? "",
    }),
    [params],
  );

  const setFilters = useCallback(
    (next: Partial<DocFilters>) => {
      setParams(
        (prev) => {
          const out = new URLSearchParams(prev);
          if (next.sources !== undefined) {
            if (next.sources.length === 0) out.delete("source");
            else out.set("source", next.sources.join(","));
          }
          if (next.search !== undefined) {
            if (!next.search) out.delete("q");
            else out.set("q", next.search);
          }
          return out;
        },
        { replace: true },
      );
    },
    [setParams],
  );

  const clear = useCallback(() => {
    setParams(
      (prev) => {
        const out = new URLSearchParams(prev);
        ["source", "q"].forEach((k) => out.delete(k));
        return out;
      },
      { replace: true },
    );
  }, [setParams]);

  const activeCount =
    (filters.sources.length > 0 ? 1 : 0) + (filters.search ? 1 : 0);

  return { filters, setFilters, clear, activeCount };
}
