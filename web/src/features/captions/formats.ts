import type { CaptionSegment, CaptionStyle } from "./types";
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

export function captionsToAss(captions: CaptionSegment[], globalStyle: CaptionStyle): string {
  const styles: string[] = [];
  const events: string[] = [];
  const sorted = captions.toSorted((a, b) => a.start - b.start);
  for (const [index, caption] of sorted.entries()) {
    const style = { ...globalStyle, ...(caption.styleOverride ?? {}) };
    const name = `Caption${index + 1}`;
    const outline = style.outlineEnabled ? Math.max(0, Math.trunc(style.outlineWidth)) : 0;
    const border = style.backgroundEnabled ? 3 : 1;
    styles.push(
      `Style: ${name},${assFontName(style.fontFamily)},${Math.max(8, Math.trunc(style.fontSize))},${assColor(style.color)},&H000000FF,${assColor(style.outlineColor)},${assColor(style.backgroundColor)},-1,0,0,0,100,100,0,0,${border},${outline},0,${assAlignment(style.position, style.align)},48,48,48,1`,
    );
    events.push(
      `Dialogue: 0,${assTimestamp(caption.start)},${assTimestamp(caption.end)},${name},,0,0,0,,${assPosition(style)}${assText(caption.text)}`,
    );
  }
  return [
    "[Script Info]",
    "ScriptType: v4.00+",
    "PlayResX: 1920",
    "PlayResY: 1080",
    "ScaledBorderAndShadow: yes",
    "WrapStyle: 0",
    "",
    "[V4+ Styles]",
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
    ...styles,
    "",
    "[Events]",
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ...events,
  ].join("\n") + "\n";
}

function assTimestamp(seconds: number): string {
  const centiseconds = Math.max(0, pythonRound(seconds * 100));
  const hours = Math.floor(centiseconds / 360_000);
  const minutes = Math.floor((centiseconds % 360_000) / 6_000);
  const remainder = centiseconds % 6_000;
  return `${hours}:${String(minutes).padStart(2, "0")}:${String(Math.floor(remainder / 100)).padStart(2, "0")}.${String(remainder % 100).padStart(2, "0")}`;
}

function assText(text: string): string {
  return text.replace(/\\/g, "\\\\").replace(/{/g, "\\{").replace(/}/g, "\\}").replace(/\r\n/g, "\\N").replace(/\n/g, "\\N");
}

function assColor(value: string): string {
  const hex = /^#([\da-f]{6})([\da-f]{2})?$/i.exec(value.trim());
  if (hex) {
    const rgb = hex[1];
    const alpha = hex[2] ? Number.parseInt(hex[2], 16) : 255;
    return `&H${(255 - alpha).toString(16).padStart(2, "0")}${rgb.slice(4, 6)}${rgb.slice(2, 4)}${rgb.slice(0, 2)}`.toUpperCase();
  }
  const rgba = /^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)(?:\s*,\s*([\d.]+))?\s*\)$/i.exec(value.trim());
  if (rgba) {
    const [red, green, blue] = [1, 2, 3].map((part) => Math.min(255, Number.parseInt(rgba[part], 10)));
    const opacity = Math.min(1, Math.max(0, Number(rgba[4] ?? 1)));
    return `&H${pythonRound((1 - opacity) * 255).toString(16).padStart(2, "0")}${[blue, green, red].map((channel) => channel.toString(16).padStart(2, "0")).join("")}`.toUpperCase();
  }
  return "&H00FFFFFF";
}

function assAlignment(position: CaptionStyle["position"], align: CaptionStyle["align"]): number {
  const row = { bottom: 0, middle: 3, top: 6 }[position] ?? 0;
  const column = { left: 1, center: 2, right: 3 }[align] ?? 2;
  return row + column;
}

function assFontName(value: string): string {
  return value.replace(/[\r\n,]/g, " ").trim() || "Apple SD Gothic Neo";
}

function pythonRound(value: number): number {
  const lower = Math.floor(value);
  const fraction = value - lower;
  if (fraction < 0.5) return lower;
  if (fraction > 0.5) return lower + 1;
  return lower % 2 === 0 ? lower : lower + 1;
}

function assPosition(style: CaptionStyle): string {
  const offsetX = Number.isFinite(style.offsetX) ? pythonRound(style.offsetX) : 0;
  const offsetY = Number.isFinite(style.offsetY) ? pythonRound(style.offsetY) : 0;
  if (!offsetX && !offsetY) return "";
  const x = { left: 48, center: 960, right: 1872 }[style.align] + offsetX;
  const y = { top: 48, middle: 540, bottom: 1032 }[style.position] + offsetY;
  return `{\\pos(${x},${y})}`;
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
