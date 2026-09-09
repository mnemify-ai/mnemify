import { useCallback } from "react";
import { useSearchParams } from "react-router-dom";

/**
 * Reads the `?tag=` query param and returns `[selectedTagId, setTag]`.
 *
 * `setTag(null)` removes the param. `setTag('tag.foo')` sets it. The hook
 * preserves any other query params on the current URL.
 */
export function useTagParam(): [string | null, (id: string | null) => void] {
  const [searchParams, setSearchParams] = useSearchParams();
  const tagId = searchParams.get("tag");

  const setTag = useCallback(
    (id: string | null) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (id === null) next.delete("tag");
          else next.set("tag", id);
          return next;
        },
        { replace: false },
      );
    },
    [setSearchParams],
  );

  return [tagId, setTag];
}
