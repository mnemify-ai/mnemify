// Timeline scrubber: rewind the map to any date and watch it grow back.
//
// Closed, it is a clock button beside the home button (top-right). Open, a
// bottom-centre strip with a date slider, a play button that sweeps from the
// first note to the last, and a "Changes" toggle that paints whatever was
// touched in the 30 days before the cutoff in the Ask-highlight accent.
// Hexes that did not exist yet at the cutoff drop to a flat ghost in
// HexField; the index behind it is util/timeline.ts.

import { useEffect, useRef, useState } from 'react';
import { Clock, Flame, Pause, Play, X } from 'lucide-react';
import { useKnowledgeMapStore } from '../store';
import {
  CHANGES_WINDOW_MS,
  DAY_MS,
  formatCutoff,
  notesBy,
  notesChangedBy,
  sliderDomain,
} from '../util/timeline';

/** Full sweep duration when playing, in ms. */
const SWEEP_MS = 9000;
const TICK_MS = 40;

export function TimelineButton({ top = 28 }: { top?: number }) {
  const open = useKnowledgeMapStore((s) => s.timelineOpen);
  const openTimeline = useKnowledgeMapStore((s) => s.openTimeline);
  const closeTimeline = useKnowledgeMapStore((s) => s.closeTimeline);
  return (
    <button
      type="button"
      style={{ top }}
      onClick={open ? closeTimeline : openTimeline}
      aria-pressed={open}
      aria-label={open ? 'Close the timeline' : 'Open the timeline'}
      title={open ? 'Close timeline' : 'Timeline — rewind the map'}
      className={[
        'glass-panel absolute right-[4.25rem] z-[5] grid h-9 w-9 place-items-center rounded-full shadow-sm transition-colors',
        open ? 'text-magenta' : 'text-muted hover:text-ink hover:bg-bone/70',
      ].join(' ')}
    >
      <Clock size={16} strokeWidth={1.75} aria-hidden />
    </button>
  );
}

export function TimelineScrubber() {
  const open = useKnowledgeMapStore((s) => s.timelineOpen);
  const timeline = useKnowledgeMapStore((s) => s.timeline);
  const index = useKnowledgeMapStore((s) => s.timelineIndex);
  const loaded = useKnowledgeMapStore((s) => s.timelineLoaded);
  const setCutoff = useKnowledgeMapStore((s) => s.setTimelineCutoff);
  const setShowChanges = useKnowledgeMapStore((s) => s.setTimelineShowChanges);
  const closeTimeline = useKnowledgeMapStore((s) => s.closeTimeline);
  // Lift above the Ask pill when both share the bottom-centre slot.
  const lifted = useKnowledgeMapStore((s) => s.askHighlight !== null);

  const [playing, setPlaying] = useState(false);
  const playingRef = useRef(false);
  playingRef.current = playing;

  // Stop playing when the scrubber closes or the index changes under it.
  useEffect(() => {
    if (!open || !index) setPlaying(false);
  }, [open, index]);

  // The interval reads the live cutoff through a ref so it stays stable
  // across ticks instead of restarting on every store update.
  const cutoffRef = useRef<number | null>(null);
  cutoffRef.current = timeline?.cutoff ?? null;
  useEffect(() => {
    if (!playing || !index) return;
    const span = Math.max(DAY_MS, index.maxMs - index.minMs);
    const step = (span / SWEEP_MS) * TICK_MS;
    const id = window.setInterval(() => {
      const next = (cutoffRef.current ?? index.minMs) + step;
      if (next >= index.maxMs) {
        setCutoff(index.maxMs);
        setPlaying(false);
      } else {
        setCutoff(next);
      }
    }, TICK_MS);
    return () => window.clearInterval(id);
  }, [playing, index, setCutoff]);

  if (!open) return null;

  const base =
    'glass-panel absolute left-1/2 z-[5] -translate-x-1/2 shadow-sm animate-fade-in motion-reduce:animate-none ' +
    (lifted ? 'bottom-[4.5rem]' : 'bottom-6');

  if (!index || !timeline) {
    return (
      <div role="status" className={`${base} flex items-center gap-2.5 rounded-full py-1.5 pl-3.5 pr-1.5`}>
        <Clock size={13} strokeWidth={1.75} className="shrink-0 text-magenta" aria-hidden />
        <span className="font-sans text-xs text-muted">
          {loaded ? 'No dates in this map’s notes — nothing to rewind.' : 'Reading note dates…'}
        </span>
        <CloseButton onClick={closeTimeline} />
      </div>
    );
  }

  const { minDay, maxDay } = sliderDomain(index);
  const cutoff = timeline.cutoff;
  const day = Math.round(cutoff / DAY_MS);
  const count = notesBy(index, cutoff);
  const changed = notesChangedBy(index, cutoff);
  const atEnd = cutoff >= index.maxMs;
  const windowDays = Math.round(CHANGES_WINDOW_MS / DAY_MS);

  function togglePlay() {
    if (playing) {
      setPlaying(false);
      return;
    }
    if (atEnd && index) setCutoff(index.minMs);
    setPlaying(true);
  }

  return (
    <div
      role="group"
      aria-label="Timeline"
      className={`${base} flex w-[min(640px,calc(100%-2rem))] items-center gap-3 rounded-2xl py-2 pl-3 pr-1.5`}
    >
      <button
        type="button"
        onClick={togglePlay}
        aria-label={playing ? 'Pause' : atEnd ? 'Replay from the first note' : 'Play forward'}
        title={playing ? 'Pause' : 'Play'}
        className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-ink text-cream transition-colors hover:bg-ink/85"
      >
        {playing ? (
          <Pause size={13} strokeWidth={2} aria-hidden />
        ) : (
          <Play size={13} strokeWidth={2} className="translate-x-px" aria-hidden />
        )}
      </button>

      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <div className="flex items-baseline justify-between gap-3 font-sans text-xs">
          <span className="truncate text-ink">
            <span className="font-medium tabular-nums">{formatCutoff(cutoff)}</span>
            <span className="text-muted">
              {' '}
              · {count} note{count === 1 ? '' : 's'}
              {timeline.showChanges && (
                <>
                  {' '}
                  · <span className="text-magenta">{changed} changed</span> in the last {windowDays} days
                </>
              )}
            </span>
          </span>
          <span className="shrink-0 text-[11px] text-muted tabular-nums">
            {formatCutoff(index.minMs)} → {formatCutoff(index.maxMs)}
          </span>
        </div>
        <input
          type="range"
          min={minDay}
          max={maxDay}
          step={1}
          value={Math.min(maxDay, Math.max(minDay, day))}
          onChange={(e) => {
            setPlaying(false);
            // Clamp into the real span so the last step lands exactly on the
            // latest note rather than on the end of its day.
            const ms = Number(e.target.value) * DAY_MS;
            setCutoff(Math.min(index.maxMs, Math.max(index.minMs, ms)));
          }}
          aria-label="Show the map as of this date"
          aria-valuetext={formatCutoff(cutoff)}
          className="h-1.5 w-full cursor-pointer accent-magenta"
        />
      </div>

      <button
        type="button"
        onClick={() => setShowChanges(!timeline.showChanges)}
        aria-pressed={timeline.showChanges}
        title={`Highlight what changed in the ${windowDays} days before this date`}
        className={[
          'inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full px-3 font-sans text-xs transition-colors',
          timeline.showChanges
            ? 'bg-magenta/15 text-magenta'
            : 'text-muted hover:bg-bone/70 hover:text-ink',
        ].join(' ')}
      >
        <Flame size={13} strokeWidth={1.75} aria-hidden />
        Changes
      </button>

      <CloseButton onClick={closeTimeline} />
    </div>
  );
}

function CloseButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label="Close the timeline"
      title="Close (Esc)"
      className="grid h-8 w-8 shrink-0 place-items-center rounded-full text-muted transition-colors hover:bg-bone/70 hover:text-ink"
    >
      <X size={13} strokeWidth={1.75} aria-hidden />
    </button>
  );
}
