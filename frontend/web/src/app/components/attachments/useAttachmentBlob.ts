// Fetch an attachment's bytes as an ArrayBuffer for renderers that parse
// client-side (DOCX via mammoth, XLSX/CSV via SheetJS). PDF.js streams the
// URL directly and does NOT use this hook.
//
// Returns ArrayBuffer (not Blob, not object URL). If a future renderer needs
// an object URL, do this in the renderer itself:
//
//   const url = useMemo(() => URL.createObjectURL(new Blob([buf])), [buf]);
//   useEffect(() => () => URL.revokeObjectURL(url), [url]);

import { useQuery } from "@tanstack/react-query";
import { API_BASE, ApiError } from "../../api/client";

export function useAttachmentBlob(inlineUrl: string | null) {
  return useQuery({
    queryKey: ["attachment-blob", inlineUrl],
    enabled: !!inlineUrl,
    staleTime: 5 * 60_000,
    gcTime: 10 * 60_000,
    retry: false,
    refetchOnWindowFocus: false,
    queryFn: async ({ signal }) => {
      const url = inlineUrl!.startsWith("http")
        ? inlineUrl!
        : `${API_BASE}${inlineUrl}`;
      const res = await fetch(url, { signal });
      if (!res.ok) {
        throw new ApiError(
          res.status,
          `${res.status} ${res.statusText}`,
          null,
        );
      }
      return await res.arrayBuffer();
    },
  });
}
