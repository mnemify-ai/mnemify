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

/**
 * Every request carries this. The backend refuses any state-changing `/api`
 * call without it: a page on another site can make the browser POST to
 * localhost, but it cannot add a custom header without a CORS preflight the
 * server never grants. Any non-empty value works; "web" says who we are.
 */
export const CLIENT_HEADER = "X-Mnemify-Client";
export const CLIENT_NAME = "web";

/**
 * Answers `apiFetch` from somewhere other than the network. The sample
 * workspace (app/demo) installs one around each of its queries and mutations
 * so the real pages it reuses read fixtures instead of the backend.
 */
export type ApiOverride = (path: string, init?: RequestInit) => Promise<unknown>;

let activeOverride: ApiOverride | null = null;

/**
 * Run `fn` with `override` answering every `apiFetch` it starts
 * *synchronously*. Synchronous on purpose: the real app keeps polling the
 * backend while the sample is open, and a scope that outlived this call
 * would capture those requests too.
 */
export function withApiOverride<R>(override: ApiOverride, fn: () => R): R {
  const prev = activeOverride;
  activeOverride = override;
  try {
    return fn();
  } finally {
    activeOverride = prev;
  }
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  // Read before the first await — that's what keeps the override scoped.
  if (activeOverride) return (await activeOverride(path, init)) as T;
  const url = path.startsWith("http") ? path : `${API_BASE}${path}`;
  const res = await fetch(url, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      [CLIENT_HEADER]: CLIENT_NAME,
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
