// DOCX preview renderer (mammoth).
//
// Converts a Word document into HTML on the client, then renders the result
// inside the existing `.doc-viewer-html` prose styles so headings, lists,
// tables, blockquotes, and inline images all match the rest of the viewer's
// typography. Inline images embedded in the DOCX are encoded as base64 data
// URIs (mammoth has them in-memory from the zip), so the rendered HTML is
// self-contained and doesn't depend on any extra network fetches.
//
// What we trade for theme consistency: mammoth deliberately strips text
// colors, specific fonts, and other inline Word formatting. That's the
// point — the doc reads as a clean article in our serif palette rather than
// fighting our chrome with Word's defaults.

import { useEffect, useState } from "react";
import mammoth from "mammoth";
import { useAttachmentBlob } from "../useAttachmentBlob";
import { sanitizeHtml } from "../../../lib/sanitizeHtml";
import { ErrorState } from "../../ui/ErrorState";
import { EmptyState } from "../../ui/EmptyState";
import { Skeleton } from "../../ui/Skeleton";
import type { RendererProps } from "../registry";

interface ConvertState {
  html: string | null;
  messages: string[];
  error: Error | null;
}

export default function DocxRenderer({
  inlineUrl,
  onChrome,
  attachment,
}: RendererProps) {
  const blob = useAttachmentBlob(inlineUrl);
  const [state, setState] = useState<ConvertState>({
    html: null,
    messages: [],
    error: null,
  });

  // Renderer reports no chrome — DOCX is a single continuous document, no
  // pagination / zoom / sheets surface in the footer.
  useEffect(() => {
    onChrome({});
  }, [onChrome]);

  // Convert when bytes arrive. Tracked via an alive flag so an unmount
  // mid-convert doesn't reach into stale state.
  useEffect(() => {
    if (!blob.data) return;
    let alive = true;
    setState({ html: null, messages: [], error: null });
    mammoth
      .convertToHtml(
        { arrayBuffer: blob.data },
        {
          // Inline images as data URIs so the HTML is self-contained.
          // DOCX bundles its images in the zip, so we already have the
          // bytes — no extra fetch needed.
          convertImage: mammoth.images.imgElement((image) =>
            image.read("base64").then((data) => ({
              src: `data:${image.contentType};base64,${data}`,
            })),
          ),
        },
      )
      .then((result) => {
        if (!alive) return;
        setState({
          html: result.value,
          messages: result.messages.map((m) => m.message),
          error: null,
        });
      })
      .catch((err: unknown) => {
        if (!alive) return;
        setState({
          html: null,
          messages: [],
          error: err instanceof Error ? err : new Error(String(err)),
        });
      });
    return () => {
      alive = false;
    };
  }, [blob.data]);

  if (blob.isLoading) {
    return <DocxSkeleton />;
  }

  if (blob.isError) {
    return (
      <div className="flex-1 min-h-0 flex items-center justify-center p-6">
        <ErrorState
          title="Couldn't load document"
          description={blob.error instanceof Error ? blob.error.message : "Unexpected error."}
          onRetry={() => void blob.refetch()}
        />
      </div>
    );
  }

  if (state.error) {
    return (
      <div className="flex-1 min-h-0 flex items-center justify-center p-6">
        <ErrorState
          title="Couldn't parse document"
          description={`${attachment.name} doesn't look like a readable DOCX.`}
        />
      </div>
    );
  }

  if (state.html === null) {
    // Bytes are in, but conversion hasn't resolved yet — show the same
    // skeleton so there's no flash of empty content.
    return <DocxSkeleton />;
  }

  if (state.html.trim() === "") {
    return (
      <div className="flex-1 min-h-0 flex items-center justify-center p-6">
        <EmptyState
          title="Empty document"
          description="This document doesn't contain any content."
        />
      </div>
    );
  }

  const clean = sanitizeHtml(state.html);

  return (
    <div className="flex-1 min-h-0 overflow-auto bg-bone/30">
      <article
        className="doc-viewer-html font-serif text-[15px] text-ink leading-relaxed bg-cream border border-hair rounded-xl shadow-sm max-w-[72ch] mx-auto my-8 px-10 py-10"
        // Self-owned content (the user's own harvested doc) and sanitized above.
        dangerouslySetInnerHTML={{ __html: clean }}
      />
    </div>
  );
}

function DocxSkeleton() {
  return (
    <div className="flex-1 min-h-0 overflow-hidden p-8" aria-busy>
      <div className="max-w-[72ch] mx-auto bg-cream border border-hair rounded-xl px-10 py-10 space-y-4">
        <Skeleton variant="line" width="60%" className="h-6" />
        <div className="space-y-2 pt-2">
          <Skeleton variant="line" width="98%" />
          <Skeleton variant="line" width="95%" />
          <Skeleton variant="line" width="100%" />
          <Skeleton variant="line" width="92%" />
        </div>
        <div className="space-y-2 pt-3">
          <Skeleton variant="line" width="40%" className="h-5" />
          <Skeleton variant="line" width="100%" />
          <Skeleton variant="line" width="88%" />
          <Skeleton variant="line" width="94%" />
        </div>
      </div>
    </div>
  );
}
