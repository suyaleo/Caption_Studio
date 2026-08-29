import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CaptionRail } from "./components/CaptionRail";
import { Inspector } from "./components/Inspector";
import { PreviewStage } from "./components/PreviewStage";
import { ProductionPanel } from "./components/ProductionPanel";
import { Timeline } from "./components/Timeline";
import { Toolbar } from "./components/Toolbar";
import {
  captionsToSrt,
  captionsToVtt,
  downloadText,
  parseCaptionText,
} from "./features/captions/formats";
import { useCaptionEditor } from "./features/captions/useCaptionEditor";
import { useProductionJobs } from "./features/production/useProductionJobs";

export function App() {
  const editor = useCaptionEditor();
  const videoRef = useRef<HTMLVideoElement>(null);
  const videoUrlRef = useRef<string | null>(null);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [mediaFile, setMediaFile] = useState<File | null>(null);
  const [currentTime, setCurrentTime] = useState(3.42);
  const [playing, setPlaying] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const showNotice = useCallback((message: string) => {
    setNotice(message);
    window.setTimeout(() => setNotice(null), 2600);
  }, []);

  const activeCaption = useMemo(
    () => editor.captions.find((caption) => currentTime >= caption.start && currentTime < caption.end),
    [currentTime, editor.captions],
  );

  const seek = useCallback((time: number) => {
    const next = Math.min(Math.max(time, 0), editor.duration);
    setCurrentTime(next);
    if (videoRef.current) videoRef.current.currentTime = next;
  }, [editor.duration]);

  const pausePlayback = useCallback(() => {
    videoRef.current?.pause();
    setPlaying(false);
  }, []);

  const selectCaptionForEditing = useCallback((id: string) => {
    editor.setSelectedId(id);
    const caption = editor.captions.find((item) => item.id === id);
    if (caption) seek(caption.start + 0.02);
    pausePlayback();
  }, [editor.captions, editor.setSelectedId, pausePlayback, seek]);

  const updateSelectedStyleWithPreview = useCallback((patch: Parameters<typeof editor.updateSelectedStyle>[0]) => {
    if (editor.selected) seek(editor.selected.start + 0.02);
    pausePlayback();
    editor.updateSelectedStyle(patch);
  }, [editor.selected, editor.updateSelectedStyle, pausePlayback, seek]);

  const applyGeneratedCaptions = useCallback((captions: Parameters<typeof editor.replaceCaptions>[0]) => {
    editor.replaceCaptions(captions);
    if (captions[0]) seek(captions[0].start + 0.02);
  }, [editor.replaceCaptions, seek]);

  const production = useProductionJobs({
    onCaptions: applyGeneratedCaptions,
    onNotice: showNotice,
  });

  const togglePlay = useCallback(() => {
    const video = videoRef.current;
    if (video) {
      if (video.paused) {
        void video.play().then(() => setPlaying(true)).catch(() => showNotice("브라우저가 재생을 막았습니다. 다시 눌러주세요."));
      } else {
        video.pause();
        setPlaying(false);
      }
      return;
    }

    setPlaying((current) => !current);
  }, [showNotice]);

  useEffect(() => {
    if (!playing || videoUrl) return;
    let animationFrame = 0;
    let previous = performance.now();
    const tick = (now: number) => {
      const elapsed = (now - previous) / 1000;
      previous = now;
      setCurrentTime((value) => {
        const next = value + elapsed;
        if (next >= editor.duration) {
          setPlaying(false);
          return 0;
        }
        return next;
      });
      animationFrame = requestAnimationFrame(tick);
    };
    animationFrame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(animationFrame);
  }, [editor.duration, playing, videoUrl]);

  const openVideo = useCallback((file: File) => {
    if (videoUrlRef.current) URL.revokeObjectURL(videoUrlRef.current);
    const url = URL.createObjectURL(file);
    videoUrlRef.current = url;
    setVideoUrl(url);
    setMediaFile(file);
    production.resetMedia();
    editor.setMediaName(file.name);
    setCurrentTime(0);
    setPlaying(false);
    showNotice(`${file.name} 영상을 열었습니다.`);
  }, [editor, production.resetMedia, showNotice]);

  useEffect(() => () => {
    if (videoUrlRef.current) URL.revokeObjectURL(videoUrlRef.current);
  }, []);

  const importCaptions = useCallback(async (file: File) => {
    const parsed = parseCaptionText(await file.text());
    if (!parsed.length) {
      showNotice("읽을 수 있는 자막 구간이 없습니다.");
      return;
    }
    editor.replaceCaptions(parsed);
    seek(parsed[0].start);
    showNotice(`${parsed.length}개 자막을 가져왔습니다.`);
  }, [editor, seek, showNotice]);

  const saveProject = useCallback(() => {
    const payload = {
      version: 1,
      projectName: editor.projectName,
      mediaName: editor.mediaName,
      duration: editor.duration,
      captions: editor.captions,
      globalStyle: editor.globalStyle,
      updatedAt: new Date().toISOString(),
    };
    downloadText(`${editor.projectName}.caption.json`, `${JSON.stringify(payload, null, 2)}\n`, "application/json");
    showNotice("프로젝트 사본을 저장했습니다.");
  }, [editor, showNotice]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement;
      const editingText = target.matches("input, textarea, [contenteditable='true']");
      if (event.code === "Space" && !editingText) {
        event.preventDefault();
        togglePlay();
      }
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        saveProject();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [saveProject, togglePlay]);

  return (
    <div className="app-shell">
      <Toolbar
        saveStatus={editor.saveStatus}
        onOpenVideo={openVideo}
        onImportCaptions={importCaptions}
        onSaveProject={saveProject}
        onExportSrt={() => downloadText(`${editor.projectName}.srt`, captionsToSrt(editor.captions), "application/x-subrip")}
        onExportVtt={() => downloadText(`${editor.projectName}.vtt`, captionsToVtt(editor.captions), "text/vtt")}
        onOpenProduction={production.show}
      />

      <div className="editor-grid">
        <CaptionRail
          captions={editor.captions}
          selectedId={editor.selectedId}
          onSelect={selectCaptionForEditing}
          onAdd={() => editor.addCaption(currentTime)}
          onDelete={editor.deleteSelected}
        />
        <PreviewStage
          videoRef={videoRef}
          videoUrl={videoUrl}
          mediaName={editor.mediaName}
          activeCaption={activeCaption}
          globalStyle={editor.globalStyle}
          onTimeUpdate={setCurrentTime}
          onDuration={editor.setDuration}
          onEnded={() => setPlaying(false)}
        />
        <Inspector
          selected={editor.selected}
          globalStyle={editor.globalStyle}
          onUpdateCaption={editor.updateCaption}
          onUpdateStyle={updateSelectedStyleWithPreview}
          onUpdateGlobalStyle={(patch) => editor.setGlobalStyle((current) => ({ ...current, ...patch }))}
        />
      </div>

      <Timeline
        captions={editor.captions}
        duration={editor.duration}
        currentTime={currentTime}
        selectedId={editor.selectedId}
        playing={playing}
        onTogglePlay={togglePlay}
        onSeek={seek}
        onSelect={selectCaptionForEditing}
        onUpdate={editor.updateCaption}
        onAdd={() => editor.addCaption(currentTime)}
      />

      <ProductionPanel
        open={production.open}
        mode={production.mode}
        mediaFile={mediaFile}
        captionCount={editor.captions.length}
        health={production.health}
        healthError={production.healthError}
        job={production.job}
        uploading={production.uploading}
        uploadProgress={production.uploadProgress}
        asrModel={production.asrModel}
        sourceLanguage={production.sourceLanguage}
        translationEnabled={production.translationEnabled}
        translationProvider={production.translationProvider}
        providerAuth={production.providerAuth}
        targetLanguage={production.targetLanguage}
        onClose={() => production.setOpen(false)}
        onMode={production.setMode}
        onModel={production.setAsrModel}
        onSourceLanguage={production.setSourceLanguage}
        onTranslationEnabled={production.setTranslationEnabled}
        onTranslationProvider={production.setTranslationProvider}
        onStartProviderLogin={() => { void production.startProviderLogin(); }}
        onTargetLanguage={production.setTargetLanguage}
        onRefreshHealth={() => void production.refreshHealth()}
        onTranscribe={() => {
          if (mediaFile) void production.transcribe(mediaFile);
        }}
        onRender={() => {
          if (mediaFile) void production.render(mediaFile, editor.captions, editor.globalStyle);
        }}
      />

      {notice ? <div className="toast" role="status">{notice}</div> : null}
    </div>
  );
}
