import { useCallback, useEffect, useMemo, useState } from "react";
import type { CaptionProject, CaptionSegment, CaptionStyle } from "./types";
import { DEFAULT_STYLE, SEED_CAPTIONS } from "./types";
import { clamp } from "./time";

const STORAGE_KEY = "caption-studio-project-v1";

function loadProject(): CaptionProject | null {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (!stored) return null;
    const parsed = JSON.parse(stored) as CaptionProject;
    if (parsed.version !== 1 || !Array.isArray(parsed.captions)) return null;
    return {
      ...parsed,
      globalStyle: { ...DEFAULT_STYLE, ...(parsed.globalStyle ?? {}) },
      captions: parsed.captions.map((caption) => ({
        ...caption,
        styleOverride: caption.styleOverride ? { ...caption.styleOverride } : undefined,
      })),
    };
  } catch {
    return null;
  }
}

export function useCaptionEditor() {
  const stored = useMemo(loadProject, []);
  const [projectName] = useState(stored?.projectName ?? "wedding-film-01");
  const [mediaName, setMediaName] = useState<string | null>(stored?.mediaName ?? null);
  const [duration, setDurationState] = useState(stored?.duration ?? 20);
  const [captions, setCaptions] = useState<CaptionSegment[]>(stored?.captions ?? SEED_CAPTIONS);
  const [globalStyle, setGlobalStyle] = useState<CaptionStyle>({ ...DEFAULT_STYLE, ...(stored?.globalStyle ?? {}) });
  const [selectedId, setSelectedId] = useState((stored?.captions ?? SEED_CAPTIONS)[1]?.id ?? null);
  const [saveStatus, setSaveStatus] = useState<"saved" | "saving">("saved");

  const selected = useMemo(
    () => captions.find((caption) => caption.id === selectedId) ?? captions[0],
    [captions, selectedId],
  );

  const sortedCaptions = useMemo(
    () => captions.toSorted((a, b) => a.start - b.start),
    [captions],
  );

  useEffect(() => {
    setSaveStatus("saving");
    const timer = window.setTimeout(() => {
      const project: CaptionProject = {
        version: 1,
        projectName,
        mediaName,
        duration,
        captions,
        globalStyle,
        updatedAt: new Date().toISOString(),
      };
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(project));
      setSaveStatus("saved");
    }, 350);
    return () => window.clearTimeout(timer);
  }, [captions, duration, globalStyle, mediaName, projectName]);

  const setDuration = useCallback((next: number) => {
    if (Number.isFinite(next) && next > 0) setDurationState(next);
  }, []);

  const updateCaption = useCallback((id: string, patch: Partial<CaptionSegment>) => {
    setCaptions((current) =>
      current.map((caption) => {
        if (caption.id !== id) return caption;
        const next = { ...caption, ...patch };
        const start = clamp(next.start, 0, Math.max(0, next.end - 0.1));
        const end = Math.max(start + 0.1, next.end);
        return { ...next, start, end };
      }),
    );
  }, []);

  const updateSelectedStyle = useCallback(
    (patch: Partial<CaptionStyle>) => {
      if (!selected) return;
      updateCaption(selected.id, {
        styleOverride: { ...(selected.styleOverride ?? {}), ...patch },
      });
    },
    [selected, updateCaption],
  );

  const addCaption = useCallback((at: number) => {
    const id = `caption-${crypto.randomUUID()}`;
    const start = clamp(at, 0, Math.max(duration - 0.2, 0));
    const segment: CaptionSegment = {
      id,
      start,
      end: Math.min(duration, start + 2.5),
      text: "새 자막",
    };
    setCaptions((current) => [...current, segment]);
    setSelectedId(id);
  }, [duration]);

  const deleteSelected = useCallback(() => {
    if (!selected) return;
    setCaptions((current) => {
      const remaining = current.filter((caption) => caption.id !== selected.id);
      setSelectedId(remaining[0]?.id ?? null);
      return remaining;
    });
  }, [selected]);

  const replaceCaptions = useCallback((next: CaptionSegment[]) => {
    setCaptions(next);
    setSelectedId(next[0]?.id ?? null);
    const lastEnd = next.reduce((max, caption) => Math.max(max, caption.end), 0);
    if (lastEnd > 0) setDurationState((current) => Math.max(current, lastEnd));
  }, []);

  return {
    projectName,
    mediaName,
    setMediaName,
    duration,
    setDuration,
    captions: sortedCaptions,
    replaceCaptions,
    globalStyle,
    setGlobalStyle,
    selected,
    selectedId,
    setSelectedId,
    saveStatus,
    updateCaption,
    updateSelectedStyle,
    addCaption,
    deleteSelected,
  };
}
