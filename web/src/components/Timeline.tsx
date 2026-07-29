import { Pause, Play, Plus, SkipBack, SkipForward, ZoomIn, ZoomOut } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import type { CaptionSegment } from "../features/captions/types";
import { clamp, formatShortClock } from "../features/captions/time";

type DragMode = "move" | "start" | "end";

interface TimelineProps {
  captions: CaptionSegment[];
  duration: number;
  currentTime: number;
  selectedId: string | null;
  playing: boolean;
  onTogglePlay: () => void;
  onSeek: (time: number) => void;
  onSelect: (id: string) => void;
  onUpdate: (id: string, patch: Partial<CaptionSegment>) => void;
  onAdd: () => void;
}

export function Timeline({
  captions,
  duration,
  currentTime,
  selectedId,
  playing,
  onTogglePlay,
  onSeek,
  onSelect,
  onUpdate,
  onAdd,
}: TimelineProps) {
  const trackRef = useRef<HTMLDivElement>(null);
  const [zoom, setZoom] = useState(1);
  const safeDuration = Math.max(duration, 1);
  const rulerMarks = useMemo(() => {
    const count = Math.max(4, Math.ceil(safeDuration / 2));
    return Array.from({ length: count + 1 }, (_, index) => (safeDuration / count) * index);
  }, [safeDuration]);

  const pointerToTime = (clientX: number) => {
    const rect = trackRef.current?.getBoundingClientRect();
    if (!rect) return 0;
    return clamp(((clientX - rect.left) / rect.width) * safeDuration, 0, safeDuration);
  };

  const startDrag = (event: React.PointerEvent, caption: CaptionSegment, mode: DragMode) => {
    event.stopPropagation();
    onSelect(caption.id);
    const originX = event.clientX;
    const rect = trackRef.current?.getBoundingClientRect();
    if (!rect) return;
    const secondsPerPixel = safeDuration / rect.width;
    const originStart = caption.start;
    const originEnd = caption.end;

    const onMove = (moveEvent: PointerEvent) => {
      const delta = (moveEvent.clientX - originX) * secondsPerPixel;
      if (mode === "start") {
        onUpdate(caption.id, { start: clamp(originStart + delta, 0, originEnd - 0.1) });
      } else if (mode === "end") {
        onUpdate(caption.id, { end: clamp(originEnd + delta, originStart + 0.1, safeDuration) });
      } else {
        const length = originEnd - originStart;
        const nextStart = clamp(originStart + delta, 0, Math.max(0, safeDuration - length));
        onUpdate(caption.id, { start: nextStart, end: nextStart + length });
      }
    };
    const onUp = () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp, { once: true });
  };

  return (
    <section className="timeline panel">
      <div className="timeline-toolbar">
        <div className="timeline-title">
          <h2>타임라인</h2>
          <span>드래그해 이동 · 양끝을 잡아 길이 조절</span>
        </div>
        <div className="transport" aria-label="재생 제어">
          <button className="icon-button" onClick={() => onSeek(0)} aria-label="처음으로"><SkipBack size={16} /></button>
          <button className="play-button" onClick={onTogglePlay} aria-label={playing ? "일시 정지" : "재생"}>
            {playing ? <Pause size={17} fill="currentColor" /> : <Play size={17} fill="currentColor" />}
          </button>
          <button className="icon-button" onClick={() => onSeek(Math.min(safeDuration, currentTime + 3))} aria-label="3초 앞으로"><SkipForward size={16} /></button>
          <code>{formatShortClock(currentTime)}</code>
          <span className="duration-divider">/</span>
          <code className="duration-code">{formatShortClock(safeDuration)}</code>
        </div>
        <div className="timeline-tools">
          <button className="icon-button" onClick={() => setZoom((value) => Math.max(0.75, value - 0.25))} aria-label="타임라인 축소"><ZoomOut size={16} /></button>
          <span>{Math.round(zoom * 100)}%</span>
          <button className="icon-button" onClick={() => setZoom((value) => Math.min(2, value + 0.25))} aria-label="타임라인 확대"><ZoomIn size={16} /></button>
          <button className="button compact-button" onClick={onAdd}><Plus size={14} /> 자막 추가</button>
        </div>
      </div>

      <div className="timeline-scroll">
        <div className="timeline-content" style={{ width: `${Math.max(100, zoom * 100)}%` }}>
          <div className="timeline-ruler">
            {rulerMarks.map((mark) => (
              <span key={mark} style={{ left: `${(mark / safeDuration) * 100}%` }}>
                {formatShortClock(mark).slice(0, 5)}
              </span>
            ))}
          </div>
          <div
            ref={trackRef}
            className="caption-track"
            onPointerDown={(event) => onSeek(pointerToTime(event.clientX))}
          >
            <span className="track-label">CC</span>
            {captions.map((caption, index) => (
              <div
                key={caption.id}
                className={`timeline-caption ${caption.id === selectedId ? "selected" : ""}`}
                style={{
                  left: `${(caption.start / safeDuration) * 100}%`,
                  width: `${Math.max(0.45, ((caption.end - caption.start) / safeDuration) * 100)}%`,
                }}
                onPointerDown={(event) => startDrag(event, caption, "move")}
                title={`${formatShortClock(caption.start)} — ${formatShortClock(caption.end)}\n${caption.text}`}
              >
                <button className="resize-handle start" aria-label={`${index + 1}번 자막 시작 조절`} onPointerDown={(event) => startDrag(event, caption, "start")} />
                <span className="timeline-caption-index">{index + 1}</span>
                <span className="timeline-caption-text">{caption.text}</span>
                <button className="resize-handle end" aria-label={`${index + 1}번 자막 종료 조절`} onPointerDown={(event) => startDrag(event, caption, "end")} />
              </div>
            ))}
            <div className="playhead" style={{ left: `${(currentTime / safeDuration) * 100}%` }}>
              <span />
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
