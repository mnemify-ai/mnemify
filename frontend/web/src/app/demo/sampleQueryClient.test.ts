import { afterEach, describe, expect, it, vi } from "vitest";
import { apiFetch } from "../api/client";
import { createSampleQueryClient } from "./sampleQueryClient";

afterEach(() => vi.unstubAllGlobals());

describe("createSampleQueryClient", () => {
  it("answers a query's apiFetch from the override, never the network", async () => {
    const network = vi.fn();
    vi.stubGlobal("fetch", network);
    const api = vi.fn(async (path: string) => ({ from: "sample", path }));
    const client = createSampleQueryClient(api);
    const data = await client.fetchQuery({
      queryKey: ["x"],
      // Same shape as the app's hooks: an async fn whose first statement awaits apiFetch.
      queryFn: async () => {
        try {
          return await apiFetch<{ from: string }>("/api/regions");
        } catch {
          return null;
        }
      },
    });
    expect(data).toEqual({ from: "sample", path: "/api/regions" });
    expect(api).toHaveBeenCalledWith("/api/regions", undefined);
    expect(network).not.toHaveBeenCalled();
  });

  it("routes mutations through the override too", async () => {
    vi.stubGlobal("fetch", vi.fn());
    const api = vi.fn(async () => ({ ok: true }));
    const client = createSampleQueryClient(api);
    const mutation = client.getMutationCache().build(client, {
      mutationFn: (id: string) => apiFetch(`/api/action-items/${id}/status`, { method: "PATCH", body: "{}" }),
    });
    await expect(mutation.execute("a1")).resolves.toEqual({ ok: true });
    expect(api).toHaveBeenCalledWith("/api/action-items/a1/status", { method: "PATCH", body: "{}" });
  });

  it("leaves apiFetch calls made outside its queries on the network", async () => {
    const network = vi.fn(async () => new Response(JSON.stringify({ real: true }), { status: 200 }));
    vi.stubGlobal("fetch", network);
    createSampleQueryClient(vi.fn());
    await expect(apiFetch("/api/terrain/current")).resolves.toEqual({ real: true });
    expect(network).toHaveBeenCalledOnce();
  });

  it("never treats fixtures as stale", () => {
    const client = createSampleQueryClient(vi.fn());
    const opts = client.defaultQueryOptions({ queryKey: ["y"], staleTime: 1000, refetchInterval: 5000 });
    expect(opts.staleTime).toBe(Infinity);
    expect(opts.refetchInterval).toBe(false);
  });
});
