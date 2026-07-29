export function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

export function formatClock(seconds: number, showMillis = true): string {
  const safe = Math.max(0, Number.isFinite(seconds) ? seconds : 0);
  const totalMillis = Math.round(safe * 1000);
  const hours = Math.floor(totalMillis / 3_600_000);
  const minutes = Math.floor((totalMillis % 3_600_000) / 60_000);
  const wholeSeconds = Math.floor((totalMillis % 60_000) / 1000);
  const millis = totalMillis % 1000;
  const base = [hours, minutes, wholeSeconds]
    .map((part) => String(part).padStart(2, "0"))
    .join(":");
  return showMillis ? `${base},${String(millis).padStart(3, "0")}` : base;
}

export function formatShortClock(seconds: number): string {
  const safe = Math.max(0, Number.isFinite(seconds) ? seconds : 0);
  const totalMillis = Math.round(safe * 1000);
  const minutes = Math.floor(totalMillis / 60_000);
  const wholeSeconds = Math.floor((totalMillis % 60_000) / 1000);
  const millis = totalMillis % 1000;
  return `${String(minutes).padStart(2, "0")}:${String(wholeSeconds).padStart(2, "0")}.${String(millis).padStart(3, "0")}`;
}

export function parseTimestamp(value: string): number {
  const normalized = value.trim().replace(",", ".");
  const parts = normalized.split(":").map(Number);
  if (parts.some((part) => !Number.isFinite(part))) return 0;
  if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
  if (parts.length === 2) return parts[0] * 60 + parts[1];
  return parts[0] ?? 0;
}
