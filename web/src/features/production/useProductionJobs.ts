import { useCallback, useEffect, useRef, useState } from "react";
import type { CaptionSegment, CaptionStyle } from "../captions/types";
import {
  createRenderJob,
  createTranscriptionJob,
  getBackendHealth,
  getProviderAuthStatus,
  startProviderDeviceLogin,
  type BackendHealth,
  type ProductionJob,
  type ProviderAuthStatus,
  uploadMedia,
  waitForJob,
} from "./api";

export type ProductionMode = "transcribe" | "render";

interface ProductionJobsOptions {
  onCaptions: (captions: CaptionSegment[]) => void;
  onNotice: (message: string) => void;
}

export function useProductionJobs({ onCaptions, onNotice }: ProductionJobsOptions) {
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<ProductionMode>("transcribe");
  const [health, setHealth] = useState<BackendHealth | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [job, setJob] = useState<ProductionJob | null>(null);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploading, setUploading] = useState(false);
  const [asrModel, setAsrModel] = useState("mlx-community/whisper-small-mlx");
  const [sourceLanguage, setSourceLanguage] = useState("auto");
  const [translationEnabled, setTranslationEnabled] = useState(false);
  const [translationProvider, setTranslationProvider] = useState<"grok" | "codex">("grok");
  const [providerAuth, setProviderAuth] = useState<ProviderAuthStatus | null>(null);
  const [targetLanguage, setTargetLanguage] = useState("ko");
  const uploadedRef = useRef<{ file: File; mediaId: string } | null>(null);
  const callbacksRef = useRef({ onCaptions, onNotice });

  useEffect(() => {
    callbacksRef.current = { onCaptions, onNotice };
  }, [onCaptions, onNotice]);

  const refreshHealth = useCallback(async () => {
    try {
      const result = await getBackendHealth();
      setHealth(result);
      setHealthError(null);
    } catch (error) {
      setHealth(null);
      setHealthError(error instanceof Error ? error.message : "작업 서버에 연결할 수 없습니다.");
    }
  }, []);

  useEffect(() => {
    void refreshHealth();
  }, [refreshHealth]);

  const refreshProviderAuth = useCallback(async (provider: "grok" | "codex" = translationProvider) => {
    try {
      setProviderAuth(await getProviderAuthStatus(provider));
    } catch {
      setProviderAuth(null);
    }
  }, [translationProvider]);

  useEffect(() => {
    void refreshProviderAuth();
  }, [refreshProviderAuth]);

  const startProviderLogin = useCallback(async () => {
    await startProviderDeviceLogin(translationProvider);
    await new Promise((resolve) => window.setTimeout(resolve, 700));
    await refreshProviderAuth(translationProvider);
  }, [refreshProviderAuth, translationProvider]);

  const show = useCallback((nextMode: ProductionMode) => {
    setMode(nextMode);
    setOpen(true);
    void refreshHealth();
  }, [refreshHealth]);

  const resetMedia = useCallback(() => {
    uploadedRef.current = null;
    setJob(null);
    setUploadProgress(0);
  }, []);

  const ensureUploaded = useCallback(async (file: File) => {
    if (uploadedRef.current?.file === file) return uploadedRef.current.mediaId;
    setUploading(true);
    setUploadProgress(0);
    try {
      const uploaded = await uploadMedia(file, setUploadProgress);
      uploadedRef.current = { file, mediaId: uploaded.media_id };
      return uploaded.media_id;
    } finally {
      setUploading(false);
    }
  }, []);

  const transcribe = useCallback(async (file: File) => {
    setJob(null);
    try {
      const mediaId = await ensureUploaded(file);
      const created = await createTranscriptionJob(mediaId, {
        asrModel,
        sourceLanguage,
        translate: translationEnabled,
        targetLanguage,
        translationProvider,
      });
      setJob(created);
      const complete = await waitForJob(created.job_id, setJob);
      const captions = complete.result?.captions ?? [];
      if (!captions.length) throw new Error("생성된 자막이 없습니다.");
      callbacksRef.current.onCaptions(captions);
      setOpen(false);
      const reviewCount = complete.result?.qa?.flags?.length ?? 0;
      callbacksRef.current.onNotice(
        translationEnabled
          ? `${captions.length}개 번역 자막을 적용했습니다. 원문도 함께 보존했습니다.`
          : reviewCount
          ? `${captions.length}개 자막을 적용했습니다. ${reviewCount}개 구간은 검토가 필요합니다.`
          : `${captions.length}개 자동 자막을 적용했습니다.`,
      );
    } catch (error) {
      setJob((current) => ({
        ...(current ?? {
          job_id: "local-error",
          kind: "transcribe",
          media_id: "",
          progress: 0,
          phase: "error",
          message: "자동 자막 생성 실패",
        }),
        status: "error",
        error: error instanceof Error ? error.message : "자동 자막을 생성하지 못했습니다.",
      }));
    }
  }, [asrModel, ensureUploaded, sourceLanguage, targetLanguage, translationEnabled, translationProvider]);

  const render = useCallback(async (
    file: File,
    captions: CaptionSegment[],
    globalStyle: CaptionStyle,
  ) => {
    setJob(null);
    try {
      const mediaId = await ensureUploaded(file);
      const created = await createRenderJob(mediaId, captions, globalStyle);
      setJob(created);
      const complete = await waitForJob(created.job_id, setJob);
      callbacksRef.current.onNotice("완성 영상이 준비됐습니다.");
      return complete;
    } catch (error) {
      setJob((current) => ({
        ...(current ?? {
          job_id: "local-error",
          kind: "render",
          media_id: "",
          progress: 0,
          phase: "error",
          message: "영상 출력 실패",
        }),
        status: "error",
        error: error instanceof Error ? error.message : "영상을 출력하지 못했습니다.",
      }));
      return null;
    }
  }, [ensureUploaded]);

  return {
    open,
    setOpen,
    mode,
    setMode,
    show,
    health,
    healthError,
    refreshHealth,
    job,
    uploading,
    uploadProgress,
    asrModel,
    setAsrModel,
    sourceLanguage,
    setSourceLanguage,
    translationEnabled,
    setTranslationEnabled,
    translationProvider,
    setTranslationProvider,
    providerAuth,
    refreshProviderAuth,
    startProviderLogin,
    targetLanguage,
    setTargetLanguage,
    resetMedia,
    transcribe,
    render,
  };
}
