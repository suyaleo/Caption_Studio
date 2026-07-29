import type { CaptionSegment, CaptionStyle } from "../captions/types";

export interface BackendHealth {
  ok: boolean;
  ffmpeg: string | null;
  ffprobe: string | null;
  ffmpeg_ass: boolean;
  mlx_whisper: boolean;
  asr?: {
    available: boolean;
    provider: "mlx-whisper" | "faster-whisper" | null;
    configured: string;
    installed: Record<string, boolean>;
    error?: string | null;
  };
  translator: {
    available: boolean;
    base_url: string;
    model: string | null;
    models: string[];
    error?: string;
  };
  workspace: string;
}

export interface ProductionJob {
  job_id: string;
  kind: "transcribe" | "render";
  media_id: string;
  status: "queued" | "running" | "complete" | "error";
  progress: number;
  phase: string;
  message: string;
  error?: string;
  download_url?: string;
  download_name?: string;
  result?: {
    captions?: CaptionSegment[];
    qa?: {
      passed: boolean;
      flags: Array<{ cue_id?: string; code?: string; message?: string }>;
      warnings?: string[];
    };
    size_bytes?: number;
    duration_seconds?: number;
    translation?: {
      provider: string;
      model: string | null;
      source_language: string;
      target_language: string;
    } | null;
  };
}

export interface TranscriptionOptions {
  asrModel: string;
  sourceLanguage: string;
  translate: boolean;
  targetLanguage: string;
}

export async function getBackendHealth(): Promise<BackendHealth> {
  return requestJson<BackendHealth>("/api/health");
}

export function uploadMedia(
  file: File,
  onProgress: (progress: number) => void,
): Promise<{ media_id: string; filename: string; size_bytes: number }> {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("POST", `/api/media?filename=${encodeURIComponent(file.name)}`);
    request.responseType = "json";
    request.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100));
    });
    request.addEventListener("load", () => {
      if (request.status >= 200 && request.status < 300) {
        resolve(request.response);
      } else {
        reject(new Error(request.response?.error ?? "영상 업로드에 실패했습니다."));
      }
    });
    request.addEventListener("error", () => reject(new Error("작업 서버에 연결할 수 없습니다.")));
    request.send(file);
  });
}

export async function createTranscriptionJob(
  mediaId: string,
  options: TranscriptionOptions,
): Promise<ProductionJob> {
  return requestJson<ProductionJob>("/api/jobs/transcribe", {
    method: "POST",
    body: JSON.stringify({
      media_id: mediaId,
      asr_model: options.asrModel,
      source_language: options.sourceLanguage,
      translate: options.translate,
      target_language: options.targetLanguage,
    }),
  });
}

export async function createRenderJob(
  mediaId: string,
  captions: CaptionSegment[],
  globalStyle: CaptionStyle,
): Promise<ProductionJob> {
  return requestJson<ProductionJob>("/api/jobs/render", {
    method: "POST",
    body: JSON.stringify({ media_id: mediaId, captions, global_style: globalStyle }),
  });
}

export async function waitForJob(
  jobId: string,
  onUpdate: (job: ProductionJob) => void,
): Promise<ProductionJob> {
  for (;;) {
    const job = await requestJson<ProductionJob>(`/api/jobs/${jobId}`);
    onUpdate(job);
    if (job.status === "complete") return job;
    if (job.status === "error") throw new Error(job.error ?? "작업을 완료하지 못했습니다.");
    await new Promise((resolve) => window.setTimeout(resolve, 700));
  }
}

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error ?? `요청 실패 (${response.status})`);
  return payload as T;
}
