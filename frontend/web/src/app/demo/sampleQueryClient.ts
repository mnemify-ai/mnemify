// A QueryClient for the sample workspace's subtree. Every query and mutation
// it runs is wrapped so the `apiFetch` calls they start are answered by the
// sample's fixtures (api/client.ts `withApiOverride`). The hooks themselves
// are the app's own: useRegion, useActionItems, useDocuments… unchanged.
//
// Fixtures never go stale, so queries don't poll or refetch on focus; an
// invalidation (after a sample mutation) re-reads the in-memory state.

import { QueryClient } from "@tanstack/react-query";
import { withApiOverride, type ApiOverride } from "../api/client";

const WRAPPED = Symbol("sample-wrapped");

type Fn = ((...args: unknown[]) => unknown) & { [WRAPPED]?: true };

function scoped(api: ApiOverride, fn: Fn): Fn {
  if (fn[WRAPPED]) return fn;
  const wrapped: Fn = (...args: unknown[]) => withApiOverride(api, () => fn(...args));
  wrapped[WRAPPED] = true;
  return wrapped;
}

export function createSampleQueryClient(api: ApiOverride): QueryClient {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, refetchOnWindowFocus: false, refetchOnReconnect: false },
      mutations: { retry: false },
    },
  });
  // Instance overrides of the two hooks every query/mutation passes through
  // (query-core calls them for observers, fetches and cache reads alike).
  const baseQuery = client.defaultQueryOptions.bind(client);
  client.defaultQueryOptions = ((options: Parameters<typeof baseQuery>[0]) => {
    const d = baseQuery(options);
    return {
      ...d,
      queryFn: typeof d.queryFn === "function" ? scoped(api, d.queryFn as Fn) : d.queryFn,
      staleTime: Infinity,
      refetchInterval: false,
      refetchOnWindowFocus: false,
      refetchOnReconnect: false,
      retry: false,
    };
  }) as typeof client.defaultQueryOptions;
  const baseMutation = client.defaultMutationOptions.bind(client);
  client.defaultMutationOptions = ((options: Parameters<typeof baseMutation>[0]) => {
    const d = baseMutation(options);
    return typeof d.mutationFn === "function" ? { ...d, mutationFn: scoped(api, d.mutationFn as Fn) } : d;
  }) as typeof client.defaultMutationOptions;
  return client;
}
