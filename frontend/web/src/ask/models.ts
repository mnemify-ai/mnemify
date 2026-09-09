import type { AskEngine } from "./types";
import {
  CLAUDE_MODELS,
  OPENAI_MODELS,
  findModelOption,
  modelOptionLabel,
  type ModelOption,
} from "../app/lib/modelCatalog";

export type AskModelOption = ModelOption;
export { CLAUDE_MODELS, OPENAI_MODELS };

export const MODEL_CATALOG: Record<AskEngine, readonly ModelOption[]> = {
  claude: CLAUDE_MODELS,
  openai: OPENAI_MODELS,
};

/** Catalog row for a stored value, matching by id or legacy alias. */
export function findModel(provider: AskEngine, model: string): ModelOption | undefined {
  return findModelOption(MODEL_CATALOG[provider], model);
}

/** Alias → full id (so "sonnet" saved by the old UI selects Claude Sonnet 5);
 *  anything unknown passes through untouched as a custom model id. */
export function normalizeModel(provider: AskEngine, model: string): string {
  return findModel(provider, model)?.id ?? model;
}

/** Human label for the composer pill; falls back to the raw id for custom models. */
export function modelLabel(provider: AskEngine, model: string): string {
  return modelOptionLabel(MODEL_CATALOG[provider], model);
}
