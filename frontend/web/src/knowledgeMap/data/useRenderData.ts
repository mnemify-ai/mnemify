// Fetch render-data.json scoped to the KnowledgeMap mount.
// Returns one of three states: loading, error, or loaded data.

import { useEffect, useState } from 'react';
import type { RenderData } from '../types';

export type RenderDataState =
  | { status: 'loading' }
  | { status: 'error'; error: string }
  | { status: 'ready'; data: RenderData };

const SUPPORTED_VERSION = 3;

export function useRenderData(url: string): RenderDataState {
  const [state, setState] = useState<RenderDataState>({ status: 'loading' });

  useEffect(() => {
    let cancelled = false;
    setState({ status: 'loading' });
    fetch(url)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status} fetching ${url}`);
        return r.json();
      })
      .then((json: RenderData) => {
        if (cancelled) return;
        if (json.version !== SUPPORTED_VERSION) {
          throw new Error(
            `Unsupported render-data version ${json.version} (expected ${SUPPORTED_VERSION})`,
          );
        }
        setState({ status: 'ready', data: json });
      })
      .catch((e) => {
        if (cancelled) return;
        setState({ status: 'error', error: String(e) });
      });
    return () => {
      cancelled = true;
    };
  }, [url]);

  return state;
}
