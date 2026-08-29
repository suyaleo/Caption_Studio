import {
  AlertTriangle,
  Check,
  Download,
  Film,
  LoaderCircle,
  Mic2,
  RefreshCw,
  X,
} from "lucide-react";
import type { ProductionMode } from "../features/production/useProductionJobs";
import type { BackendHealth, ProductionJob, ProviderAuthStatus } from "../features/production/api";

interface ProductionPanelProps {
  open: boolean;
  mode: ProductionMode;
  mediaFile: File | null;
  captionCount: number;
  health: BackendHealth | null;
  healthError: string | null;
  job: ProductionJob | null;
  uploading: boolean;
  uploadProgress: number;
  asrModel: string;
  sourceLanguage: string;
  translationEnabled: boolean;
  translationProvider: "grok" | "codex";
  providerAuth: ProviderAuthStatus | null;
  targetLanguage: string;
  onClose: () => void;
  onMode: (mode: ProductionMode) => void;
  onModel: (model: string) => void;
  onSourceLanguage: (language: string) => void;
  onTranslationEnabled: (enabled: boolean) => void;
  onTranslationProvider: (provider: "grok" | "codex") => void;
  onStartProviderLogin: () => void;
  onTargetLanguage: (language: string) => void;
  onRefreshHealth: () => void;
  onTranscribe: () => void;
  onRender: () => void;
}

export function ProductionPanel({
  open,
  mode,
  mediaFile,
  captionCount,
  health,
  healthError,
  job,
  uploading,
  uploadProgress,
  asrModel,
  sourceLanguage,
  translationEnabled,
  translationProvider,
  providerAuth,
  targetLanguage,
  onClose,
  onMode,
  onModel,
  onSourceLanguage,
  onTranslationEnabled,
  onTranslationProvider,
  onStartProviderLogin,
  onTargetLanguage,
  onRefreshHealth,
  onTranscribe,
  onRender,
}: ProductionPanelProps) {
  if (!open) return null;
  const active = uploading || job?.status === "queued" || job?.status === "running";
  const progress = uploading ? Math.round(uploadProgress * 0.18) : job?.progress ?? 0;
  const qaFlags = job?.result?.qa?.flags ?? [];
  const translatorReady = Boolean(providerAuth?.available);
  const asrReady = Boolean(health?.asr?.available ?? health?.mlx_whisper);
  const asrProvider = health?.asr?.provider === "faster-whisper" ? "faster-whisper · Docker" : "mlx-whisper · macOS";
  const canRun = mode === "transcribe"
    ? Boolean(asrReady && health?.ffmpeg && (!translationEnabled || translatorReady))
    : Boolean(health?.ffmpeg_ass);

  return (
    <div className="production-backdrop" role="presentation" onMouseDown={(event) => {
      if (event.currentTarget === event.target && !active) onClose();
    }}>
      <section className="production-panel" role="dialog" aria-modal="true" aria-labelledby="production-title">
        <header className="production-header">
          <div>
            <h2 id="production-title">제작 센터</h2>
            <p>원본 영상에서 자막 생성부터 완성 MP4까지</p>
          </div>
          <button className="icon-button" onClick={onClose} disabled={active} aria-label="제작 센터 닫기"><X size={17} /></button>
        </header>

        <div className="production-tabs" role="tablist">
          <button className={mode === "transcribe" ? "active" : ""} onClick={() => onMode("transcribe")} role="tab" aria-selected={mode === "transcribe"}>
            <Mic2 size={15} /> 자동 자막
          </button>
          <button className={mode === "render" ? "active" : ""} onClick={() => onMode("render")} role="tab" aria-selected={mode === "render"}>
            <Film size={15} /> 영상 출력
          </button>
        </div>

        <div className="production-body">
          <div className="runtime-checks">
            <RuntimeRow label="음성 인식" ready={asrReady} detail={asrReady ? `${asrProvider} 준비됨` : "Whisper 실행 환경 필요"} />
            <RuntimeRow label="영상 출력" ready={Boolean(health?.ffmpeg_ass)} detail={health?.ffmpeg_ass ? "FFmpeg + libass 준비됨" : "ffmpeg-full 필요"} />
            <RuntimeRow
              label="AI 번역"
              ready={translatorReady}
              detail={translatorReady ? `${translationProvider === "grok" ? "Grok" : "Codex"} OAuth 준비됨` : "OAuth 로그인 필요"}
            />
            <section className="oauth-access" aria-label="AI 번역 OAuth 로그인">
              <div>
                <strong>AI 번역 OAuth</strong>
                <small>이 Studio에만 저장됩니다.</small>
              </div>
              <label>
                <span>공급자</span>
                <select
                  value={translationProvider}
                  onChange={(event) => onTranslationProvider(event.currentTarget.value as "grok" | "codex")}
                  disabled={active}
                >
                  <option value="grok">Grok OAuth</option>
                  <option value="codex">OpenAI Codex OAuth</option>
                </select>
              </label>
              <button className="text-button oauth-login" onClick={onStartProviderLogin} disabled={active}>
                {translatorReady ? "다시 로그인" : "장치 로그인 시작"}
              </button>
              {!translatorReady ? <p>{providerAuth?.error ?? "선택한 공급자의 OAuth 로그인이 필요합니다."}</p> : null}
              {providerAuth?.login?.instructions ? <pre>{providerAuth.login.instructions}</pre> : null}
            </section>
            {healthError ? (
              <button className="runtime-retry" onClick={onRefreshHealth}><RefreshCw size={13} /> 서버 다시 확인</button>
            ) : null}
          </div>

          {!mediaFile ? (
            <div className="production-empty">
              <Film size={23} />
              <strong>먼저 영상을 열어주세요</strong>
              <p>상단의 ‘영상 열기’에서 작업할 원본을 선택하면 이곳에서 다음 단계로 진행할 수 있습니다.</p>
            </div>
          ) : (
            <>
              <div className="source-summary">
                <span>원본 영상</span>
                <strong>{mediaFile.name}</strong>
                <code>{formatBytes(mediaFile.size)}</code>
              </div>

              {mode === "transcribe" ? (
                <div className="production-form">
                  <label className="field">
                    <span>음성 인식 모델</span>
                    <select value={asrModel} onChange={(event) => onModel(event.currentTarget.value)} disabled={active}>
                      <option value="mlx-community/whisper-small-mlx">Small · 권장</option>
                      <option value="mlx-community/whisper-tiny">Tiny · 빠른 확인</option>
                      <option value="mlx-community/whisper-large-v3-turbo">Large v3 Turbo · 최고 품질</option>
                    </select>
                  </label>
                  <div className="field-grid production-language-grid">
                    <label className="field">
                      <span>원본 언어</span>
                      <select value={sourceLanguage} onChange={(event) => onSourceLanguage(event.currentTarget.value)} disabled={active}>
                        <option value="auto">자동 감지 · 권장</option>
                        {LANGUAGES.map(([code, label]) => <option key={code} value={code}>{label}</option>)}
                      </select>
                    </label>
                    <label className="field">
                      <span>번역 언어</span>
                      <select value={targetLanguage} onChange={(event) => onTargetLanguage(event.currentTarget.value)} disabled={active || !translationEnabled}>
                        {LANGUAGES.map(([code, label]) => <option key={code} value={code}>{label}</option>)}
                      </select>
                    </label>
                  </div>
                  <label className="translation-switch-row">
                    <span>
                      <strong>번역 자막 추가</strong>
                      <small>선택한 Studio 전용 OAuth 세션으로 번역합니다.</small>
                    </span>
                    <input
                      type="checkbox"
                      checked={translationEnabled}
                      onChange={(event) => onTranslationEnabled(event.currentTarget.checked)}
                      disabled={active}
                    />
                  </label>
                  {translationEnabled && !translatorReady ? (
                    <div className="translation-unavailable">
                      <AlertTriangle size={13} /> {providerAuth?.error ?? "선택한 공급자의 OAuth 로그인이 필요합니다."} 상단 OAuth 영역에서 장치 로그인을 시작하세요.
                    </div>
                  ) : null}
                  <p className="form-note">첫 실행은 모델을 내려받기 때문에 시간이 더 걸릴 수 있습니다. 결과는 현재 자막 목록을 교체하며, 불확실한 구간은 검토 대상으로 표시합니다.</p>
                </div>
              ) : (
                <div className="render-summary">
                  <div><span>출력 형식</span><strong>MP4 · H.264 · AAC</strong></div>
                  <div><span>적용 자막</span><strong>{captionCount}개 구간</strong></div>
                  <p>현재 편집기의 문구·시간·크기·색상·외곽선·배경·위치를 그대로 사용합니다.</p>
                </div>
              )}

              {(active || job) ? (
                <JobStatus job={job} uploading={uploading} progress={progress} qaFlagCount={qaFlags.length} />
              ) : null}
            </>
          )}
        </div>

        <footer className="production-footer">
          <span>{canRun ? "로컬 처리 · 원본이 외부로 전송되지 않습니다" : "필수 실행 환경을 확인하세요"}</span>
          {job?.status === "complete" && job.kind === "render" && job.download_url ? (
            <a className="button button-primary" href={job.download_url} download={job.download_name}>
              <Download size={15} /> 완성 MP4 다운로드
            </a>
          ) : (
            <button
              className="button button-primary production-run"
              onClick={mode === "transcribe" ? onTranscribe : onRender}
              disabled={!mediaFile || active || !canRun || (mode === "render" && captionCount === 0)}
            >
              {active ? <LoaderCircle className="rotating" size={15} /> : mode === "transcribe" ? <Mic2 size={15} /> : <Film size={15} />}
              {active ? "처리 중" : mode === "transcribe" ? "자동 자막 시작" : "완성 영상 만들기"}
            </button>
          )}
        </footer>
      </section>
    </div>
  );
}

function RuntimeRow({ label, ready, detail }: { label: string; ready: boolean; detail: string }) {
  return (
    <div className="runtime-row">
      <span className={ready ? "ready" : "missing"}>{ready ? <Check size={12} /> : <AlertTriangle size={12} />}</span>
      <strong>{label}</strong>
      <small>{detail}</small>
    </div>
  );
}

function JobStatus({
  job,
  uploading,
  progress,
  qaFlagCount,
}: {
  job: ProductionJob | null;
  uploading: boolean;
  progress: number;
  qaFlagCount: number;
}) {
  const errored = job?.status === "error";
  const complete = job?.status === "complete";
  return (
    <div className={`job-status ${errored ? "error" : complete ? "complete" : ""}`} aria-live="polite">
      <div className="job-status-heading">
        <span>{errored ? <AlertTriangle size={15} /> : complete ? <Check size={15} /> : <LoaderCircle className="rotating" size={15} />}</span>
        <strong>{errored ? "작업 실패" : uploading ? "원본 업로드 중" : job?.message ?? "작업 준비 중"}</strong>
        <code>{Math.max(0, Math.min(100, progress))}%</code>
      </div>
      <div className="progress-track"><span style={{ width: `${Math.max(0, Math.min(100, progress))}%` }} /></div>
      {errored ? <p>{job?.error}</p> : null}
      {complete && job?.kind === "transcribe" ? (
        <p>{qaFlagCount ? `${qaFlagCount}개 구간을 직접 들어보고 확인하세요.` : "모든 자동 검사를 통과했습니다."}</p>
      ) : null}
      {complete && job?.kind === "render" && job.result?.size_bytes ? <p>{formatBytes(job.result.size_bytes)} 완성 파일이 준비됐습니다.</p> : null}
    </div>
  );
}

function formatBytes(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

const LANGUAGES = [
  ["ko", "한국어"],
  ["en", "영어"],
  ["ja", "일본어"],
  ["zh", "중국어"],
  ["es", "스페인어"],
  ["fr", "프랑스어"],
  ["de", "독일어"],
  ["ru", "러시아어"],
] as const;

function shortModel(model?: string | null): string {
  if (!model) return "모델 준비됨";
  return model.length > 24 ? `${model.slice(0, 21)}…` : model;
}
