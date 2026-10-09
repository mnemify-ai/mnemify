import { apiUrl, CLIENT_HEADER, CLIENT_NAME } from "./client";

/**
 * `POST /api/regions/{id}/overview/refresh` — streams the re-synthesized
 * brief as `delta` events and ends with `done {text}`. Same BYOK contract as
 * `/api/ask`: the chat key rides in `Authorization` and is never stored.
 */
export async function streamOverviewRefresh(
  regionId: string,
  body: { provider: string; model: string },
  key: string,
  onDelta: (text: string) => void,
  signal?: AbortSignal,
): Promise<{ text: string; created_at: string }> {
  const res = await fetch(apiUrl(`/api/regions/${encodeURIComponent(regionId)}/overview/refresh`), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      [CLIENT_HEADER]: CLIENT_NAME,
      ...(key ? { Authorization: `Bearer ${key}` } : {}),
    },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok || !res.body) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const j = (await res.json()) as { detail?: unknown };
      if (typeof j.detail === "string") detail = j.detail;
    } catch {
      /* not JSON */
    }
    throw new Error(detail);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let event: string | null = null;
  let data = "";
  let result: { text: string; created_at: string } | null = null;
  let error: string | null = null;
  const dispatch = () => {
    if (!event || !data) return;
    try {
      const payload = JSON.parse(data) as Record<string, unknown>;
      if (event === "delta") onDelta(String(payload.text ?? ""));
      else if (event === "done") result = { text: String(payload.text ?? ""), created_at: String(payload.created_at ?? "") };
      else if (event === "error") error = String(payload.message ?? "refresh failed");
    } catch {
      /* malformed frame */
    }
  };
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let nl: number;
    while ((nl = buffer.indexOf("\n")) !== -1) {
      const line = buffer.slice(0, nl).replace(/\r$/, "");
      buffer = buffer.slice(nl + 1);
      if (line === "") {
        dispatch();
        event = null;
        data = "";
      } else if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) data += line.slice(5).trim();
    }
  }
  dispatch();
  if (error) throw new Error(error);
  if (!result) throw new Error("the refresh ended without a brief");
  return result;
}
