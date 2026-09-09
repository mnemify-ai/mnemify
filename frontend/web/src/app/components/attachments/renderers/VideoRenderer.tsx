// Video preview renderer (mp4 / mov / m4v / webm / ogv).
//
// The browser's <video> element does all the heavy lifting — decoding,
// buffering, range-request streaming, seeking — so this file is just a
// themed control surface over the HTMLMediaElement API to match the
// app's bone/cream/magenta design language (the default browser controls
// look off-brand inside our modal).
//
// Scope: play/pause, scrubber with buffered-progress, current/total time,
// volume + mute, fullscreen, click-to-pause, keyboard shortcuts. No
// dependencies. Reports empty ChromeState — the player owns its own UI.
//
// Failure mode: a container/codec the browser can't decode (e.g. some .mov
// or .avi) fires <video> onError → themed ErrorState with a download link.

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
} from "react";
import {
  Play,
  Pause,
  Volume2,
  VolumeX,
  Maximize,
  Minimize,
} from "lucide-react";
import { ErrorState } from "../../ui/ErrorState";
import { cn } from "../../../lib/cn";
import type { RendererProps } from "../registry";

function formatTime(s: number): string {
  if (!isFinite(s) || s < 0) s = 0;
  const total = Math.floor(s);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const sec = total % 60;
  const ss = String(sec).padStart(2, "0");
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${ss}`;
  return `${m}:${ss}`;
}

const SEEK_STEP = 5; // seconds for arrow-key seek
const VOLUME_STEP = 0.1;

export default function VideoRenderer({
  inlineUrl,
  downloadUrl,
  attachment,
  onChrome,
}: RendererProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const trackRef = useRef<HTMLDivElement>(null);

  const [playing, setPlaying] = useState(false);
  const [duration, setDuration] = useState(0);
  const [currentTime, setCurrentTime] = useState(0);
  const [buffered, setBuffered] = useState(0);
  const [volume, setVolume] = useState(1);
  const [muted, setMuted] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [scrubbing, setScrubbing] = useState(false);
  const [failed, setFailed] = useState(false);

  // The player owns its UI; no footer chrome.
  useEffect(() => {
    onChrome({});
  }, [onChrome]);

  // ----- Imperative helpers -----------------------------------------------
  const togglePlay = useCallback(() => {
    const v = videoRef.current;
    if (!v) return;
    if (v.paused) void v.play().catch(() => {});
    else v.pause();
  }, []);

  const seekTo = useCallback((time: number) => {
    const v = videoRef.current;
    if (!v || !isFinite(v.duration)) return;
    v.currentTime = Math.max(0, Math.min(v.duration, time));
  }, []);

  const setVolumeTo = useCallback((next: number) => {
    const v = videoRef.current;
    if (!v) return;
    const clamped = Math.max(0, Math.min(1, +next.toFixed(2)));
    v.volume = clamped;
    // Setting a non-zero volume implicitly unmutes; zero acts like mute.
    v.muted = clamped === 0;
  }, []);

  const toggleMute = useCallback(() => {
    const v = videoRef.current;
    if (!v) return;
    v.muted = !v.muted;
    if (!v.muted && v.volume === 0) v.volume = 0.5;
  }, []);

  const toggleFullscreen = useCallback(() => {
    const el = containerRef.current;
    if (!el) return;
    if (document.fullscreenElement) void document.exitFullscreen().catch(() => {});
    else void el.requestFullscreen().catch(() => {});
  }, []);

  // ----- Fullscreen state sync --------------------------------------------
  useEffect(() => {
    const onFsChange = () => setIsFullscreen(!!document.fullscreenElement);
    document.addEventListener("fullscreenchange", onFsChange);
    return () => document.removeEventListener("fullscreenchange", onFsChange);
  }, []);

  // ----- Keyboard shortcuts -----------------------------------------------
  // AttachmentViewer's modal-global handler only acts when chrome.pagination/
  // sheets/zoom are set (none here), so arrows don't conflict. We still skip
  // when focus is in a form field, for parity.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const tgt = e.target as HTMLElement | null;
      if (
        tgt &&
        (tgt.tagName === "INPUT" ||
          tgt.tagName === "TEXTAREA" ||
          tgt.isContentEditable)
      ) {
        return;
      }
      switch (e.key) {
        case " ":
        case "k":
          e.preventDefault();
          togglePlay();
          break;
        case "ArrowRight":
          e.preventDefault();
          seekTo((videoRef.current?.currentTime ?? 0) + SEEK_STEP);
          break;
        case "ArrowLeft":
          e.preventDefault();
          seekTo((videoRef.current?.currentTime ?? 0) - SEEK_STEP);
          break;
        case "ArrowUp":
          e.preventDefault();
          setVolumeTo((videoRef.current?.volume ?? 0) + VOLUME_STEP);
          break;
        case "ArrowDown":
          e.preventDefault();
          setVolumeTo((videoRef.current?.volume ?? 0) - VOLUME_STEP);
          break;
        case "f":
          e.preventDefault();
          toggleFullscreen();
          break;
        case "m":
          e.preventDefault();
          toggleMute();
          break;
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [togglePlay, seekTo, setVolumeTo, toggleFullscreen, toggleMute]);

  // ----- Scrubber pointer handling ----------------------------------------
  const seekFromPointer = useCallback(
    (clientX: number) => {
      const track = trackRef.current;
      const v = videoRef.current;
      if (!track || !v || !isFinite(v.duration)) return;
      const rect = track.getBoundingClientRect();
      const fraction = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
      v.currentTime = fraction * v.duration;
      setCurrentTime(v.currentTime);
    },
    [],
  );

  const onTrackPointerDown = (e: ReactPointerEvent) => {
    e.preventDefault();
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
    setScrubbing(true);
    seekFromPointer(e.clientX);
  };
  const onTrackPointerMove = (e: ReactPointerEvent) => {
    if (!scrubbing) return;
    seekFromPointer(e.clientX);
  };
  const onTrackPointerUp = (e: ReactPointerEvent) => {
    if (!scrubbing) return;
    (e.target as HTMLElement).releasePointerCapture(e.pointerId);
    setScrubbing(false);
  };

  if (failed) {
    return (
      <div className="flex-1 min-h-0 flex items-center justify-center p-6">
        <ErrorState
          title="Can't play this video"
          description="The browser can't decode this video's format or codec. Download it to play in a native app."
          onRetry={() => {
            const a = document.createElement("a");
            a.href = downloadUrl;
            a.download = attachment.name;
            a.rel = "noopener";
            document.body.appendChild(a);
            a.click();
            a.remove();
          }}
          retryLabel="Download"
        />
      </div>
    );
  }

  const playedPct = duration > 0 ? (currentTime / duration) * 100 : 0;
  const bufferedPct = duration > 0 ? (buffered / duration) * 100 : 0;

  return (
    <div
      ref={containerRef}
      className="attachment-video relative flex-1 min-h-0 flex flex-col bg-black"
    >
      {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
      <video
        ref={videoRef}
        src={inlineUrl}
        className="flex-1 min-h-0 w-full object-contain bg-black"
        onClick={togglePlay}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onLoadedMetadata={(e) => setDuration(e.currentTarget.duration)}
        onTimeUpdate={(e) => {
          if (!scrubbing) setCurrentTime(e.currentTarget.currentTime);
        }}
        onProgress={(e) => {
          const v = e.currentTarget;
          if (v.buffered.length > 0) {
            setBuffered(v.buffered.end(v.buffered.length - 1));
          }
        }}
        onVolumeChange={(e) => {
          setVolume(e.currentTarget.volume);
          setMuted(e.currentTarget.muted);
        }}
        onError={() => setFailed(true)}
      />

      {/* Control bar */}
      <div className="shrink-0 px-4 pt-3 pb-3 bg-black/90 border-t border-white/10">
        {/* Scrubber */}
        <div
          ref={trackRef}
          role="slider"
          aria-label="Seek"
          aria-valuemin={0}
          aria-valuemax={Math.round(duration)}
          aria-valuenow={Math.round(currentTime)}
          tabIndex={0}
          onPointerDown={onTrackPointerDown}
          onPointerMove={onTrackPointerMove}
          onPointerUp={onTrackPointerUp}
          className="group relative h-4 flex items-center cursor-pointer touch-none"
        >
          <div className="relative w-full h-1 rounded-full bg-white/20 overflow-hidden">
            <div
              className="absolute inset-y-0 left-0 bg-white/30"
              style={{ width: `${bufferedPct}%` }}
            />
            <div
              className="absolute inset-y-0 left-0 bg-magenta"
              style={{ width: `${playedPct}%` }}
            />
          </div>
          <div
            className="absolute h-3 w-3 rounded-full bg-magenta shadow ring-2 ring-black -translate-x-1/2 opacity-0 group-hover:opacity-100 transition-opacity"
            style={{ left: `${playedPct}%` }}
            aria-hidden
          />
        </div>

        {/* Buttons row */}
        <div className="mt-2 flex items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <ControlButton
              label={playing ? "Pause" : "Play"}
              onClick={togglePlay}
            >
              {playing ? (
                <Pause size={18} strokeWidth={2} aria-hidden fill="currentColor" />
              ) : (
                <Play size={18} strokeWidth={2} aria-hidden fill="currentColor" />
              )}
            </ControlButton>
            <span className="font-mono text-[11px] text-white/80 tabular-nums select-none">
              {formatTime(currentTime)} / {formatTime(duration)}
            </span>
          </div>

          <div className="flex items-center gap-2">
            <div className="flex items-center gap-1.5 group/vol">
              <ControlButton
                label={muted || volume === 0 ? "Unmute" : "Mute"}
                onClick={toggleMute}
              >
                {muted || volume === 0 ? (
                  <VolumeX size={18} strokeWidth={1.75} aria-hidden />
                ) : (
                  <Volume2 size={18} strokeWidth={1.75} aria-hidden />
                )}
              </ControlButton>
              <input
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={muted ? 0 : volume}
                onChange={(e) => setVolumeTo(parseFloat(e.target.value))}
                aria-label="Volume"
                className="video-volume w-16 accent-magenta cursor-pointer"
              />
            </div>
            <ControlButton
              label={isFullscreen ? "Exit fullscreen" : "Fullscreen"}
              onClick={toggleFullscreen}
            >
              {isFullscreen ? (
                <Minimize size={18} strokeWidth={1.75} aria-hidden />
              ) : (
                <Maximize size={18} strokeWidth={1.75} aria-hidden />
              )}
            </ControlButton>
          </div>
        </div>
      </div>
    </div>
  );
}

function ControlButton({
  label,
  onClick,
  children,
}: {
  label: string;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      className={cn(
        "inline-flex items-center justify-center h-9 w-9 rounded-full",
        "text-white/80 hover:text-white hover:bg-white/10 transition-colors",
      )}
    >
      {children}
    </button>
  );
}
