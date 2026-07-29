import type { CaptionSegment } from "./types";
import { formatClock, parseTimestamp } from "./time";

const TIMING_LINE = /^(\d{1,2}:)?\d{1,2}:\d{2}[,.]\d{3}\s*-->\s*(\d{1,2}:)?\d{1,2}:\d{2}[,.]\d{3}/;

export function parseCaptionText(source: string): CaptionSegment[] {
  const normalized = source.replace(/^WEBVTT[^\n]*\n+/i, "").replace(/\r\n/g, "\n");
  const blocks = normalized.split(/\n{2,}/).map((block) => block.trim()).filter(Boolean);
  const segments: CaptionSegment[] = [];

  for (const block of blocks) {
    const lines = block.split("\n").map((line) => line.trimEnd());
    const timingIndex = lines.findIndex((line) => TIMING_LINE.test(line.trim()));
    if (timingIndex === -1) continue;
    const [rawStart, rawEndWithSettings] = lines[timingIndex].split(/\s*-->\s*/);
    const rawEnd = rawEndWithSettings.split(/\s+/)[0];
    const start = parseTimestamp(rawStart);
    const end = parseTimestamp(rawEnd);
    if (!(end > start)) continue;
    const text = lines.slice(timingIndex + 1).join("\n").trim();
    if (!text) continue;
    segments.push({
      id: `caption-${crypto.randomUUID()}`,
      start,
      end,
      text,
    });
  }

  return segments.toSorted((a, b) => a.start - b.start);
}

export function captionsToSrt(captions: CaptionSegment[]): string {
  return captions
    .toSorted((a, b) => a.start - b.start)
    .map(
      (caption, index) =>
        `${index + 1}\n${formatClock(caption.start)} --> ${formatClock(caption.end)}\n${caption.text.trim()}`,
    )
    .join("\n\n") + "\n";
}

export function captionsToVtt(captions: CaptionSegment[]): string {
  const body = captions
    .toSorted((a, b) => a.start - b.start)
    .map(
      (caption) =>
        `${formatClock(caption.start).replace(",", ".")} --> ${formatClock(caption.end).replace(",", ".")}\n${caption.text.trim()}`,
    )
    .join("\n\n");
  return `WEBVTT\n\n${body}\n`;
}

export function downloadText(filename: string, text: string, mimeType: string): void {
  const blob = new Blob([text], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
