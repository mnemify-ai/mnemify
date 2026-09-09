/**
 * Typed fetch wrapper for the Mnemify backend.
 *
 * Reads `VITE_API_BASE_URL` for SSE pinning + as an absolute-URL fallback.
 * Defaults to '' (empty), which means same-origin — relying on Vite's dev
 * proxy for `/api` paths.
 */

export const API_BASE: string =
  (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "") ??
  "";

export class ApiError extends Error {
  status: number;
  body: unknown;
  constructor(status: number, message: string, body?: unknown) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const url = path.startsWith("http") ? path : `${API_BASE}${path}`;
  const res = await fetch(url, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) {
    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      /* swallow */
    }
    const msg =
      (body && typeof body === "object" && "detail" in (body as object)
        ? String((body as { detail: unknown }).detail)
        : null) ?? `${res.status} ${res.statusText}`;
    throw new ApiError(res.status, msg, body);
  }
  // 204 / empty body
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/** Resolve a backend URL for non-fetch consumers (EventSource etc.). */
export function apiUrl(path: string): string {
  return path.startsWith("http") ? path : `${API_BASE}${path}`;
}
