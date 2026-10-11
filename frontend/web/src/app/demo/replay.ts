// Timing for replaying a recorded /api/ask answer in the sample workspace.
// A real agentic answer can take a minute; the replay keeps its shape (the
// map lights up, the agent's steps tick by, then the answer streams in with
// its citations). The exploring phase is shortened; the text streams at a
// believable model pace rather than appearing all at once.

import { toAskEvent, type AskEvent } from "../../ask/askEvents";

export type ScheduledEvent = { atMs: number; ev: AskEvent };

export type ReplayOptions = {
  /** Budget for everything before the first word of the answer. */
  preludeMs?: number;
  /** Streaming speed for the answer text. */
  charsPerSecond?: number;
  /** Everything at t=0 (still in order) — for prefers-reduced-motion. */
  reducedMotion?: boolean;
};

const MIN_STEP_GAP_MS = 220;
// About what a fast model streams to a reader.
const CHARS_PER_SECOND = 150;
const WORDS_PER_CHUNK = 2;

/** Split text into ~3-word pieces, keeping every character (whitespace
 *  included) so the pieces concatenate back to the original exactly. */
export function chunkText(text: string, wordsPerChunk = WORDS_PER_CHUNK): string[] {
  const tokens = text.match(/\S+\s*|\s+/g) ?? [];
  const out: string[] = [];
  for (let i = 0; i < tokens.length; i += wordsPerChunk) out.push(tokens.slice(i, i + wordsPerChunk).join(""));
  return out;
}

export function scheduleReplay(
  recorded: readonly { t: number; event: string; data: unknown }[],
  { preludeMs = 5000, charsPerSecond = CHARS_PER_SECOND, reducedMotion = false }: ReplayOptions = {},
): ScheduledEvent[] {
  const events = recorded
    .map((r) => ({ t: r.t, ev: toAskEvent(r.event, r.data) }))
    .filter((r): r is { t: number; ev: AskEvent } => r.ev !== null);

  // Re-split the answer text into even pieces regardless of how the model
  // happened to chunk it.
  const expanded: { t: number; ev: AskEvent }[] = [];
  for (const r of events) {
    if (r.ev.kind === "delta") {
      for (const piece of chunkText(r.ev.text)) expanded.push({ t: r.t, ev: { kind: "delta", text: piece } });
    } else {
      expanded.push(r);
    }
  }
  if (reducedMotion) return expanded.map((r) => ({ atMs: 0, ev: r.ev }));

  // The answer starts at the first text after the agent's last tool step;
  // anything streamed between steps is part of the exploring phase.
  let lastStep = -1;
  expanded.forEach((r, i) => {
    if (r.ev.kind === "agent_step") lastStep = i;
  });
  const firstDelta = expanded.findIndex((r, i) => i > lastStep && r.ev.kind === "delta");
  const preludeEnd = firstDelta === -1 ? expanded.length : firstDelta;
  const preludeSpan = Math.max(1, expanded[preludeEnd - 1]?.t ?? 1);
  const scale = Math.min(1, preludeMs / preludeSpan);

  const out: ScheduledEvent[] = [];
  let cursor = 0;
  for (let i = 0; i < preludeEnd; i++) {
    const { t, ev } = expanded[i];
    // Steps and citations get a visible beat each; status ticks don't.
    const gap = ev.kind === "status" ? 0 : MIN_STEP_GAP_MS;
    cursor = Math.max(i === 0 ? 0 : cursor + gap, Math.round(t * scale));
    out.push({ atMs: cursor, ev });
  }

  const msPerChar = 1000 / charsPerSecond;
  cursor += preludeEnd > 0 ? 400 : 0;
  for (let i = preludeEnd; i < expanded.length; i++) {
    const { ev } = expanded[i];
    if (ev.kind === "delta") {
      // Uneven like real token streaming: ±35% around the steady rate, with
      // a deterministic wobble so tests (and replays) are repeatable.
      const wobble = 0.65 + 0.7 * ((Math.sin(i * 12.9898) * 43758.5453) % 1 + 1) % 1;
      cursor += Math.max(16, Math.round(ev.text.length * msPerChar * wobble));
    } else {
      cursor += 120;
    }
    out.push({ atMs: cursor, ev });
  }
  return out;
}
