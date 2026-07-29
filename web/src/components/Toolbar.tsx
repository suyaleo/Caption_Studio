import {
  Check,
  Download,
  FileInput,
  Film,
  FolderOpen,
  Mic2,
  Save,
} from "lucide-react";
import { useRef } from "react";

interface ToolbarProps {
  saveStatus: "saved" | "saving";
  onOpenVideo: (file: File) => void;
  onImportCaptions: (file: File) => void;
  onSaveProject: () => void;
  onExportSrt: () => void;
  onExportVtt: () => void;
  onOpenProduction: (mode: "transcribe" | "render") => void;
}

export function Toolbar({
  saveStatus,
  onOpenVideo,
  onImportCaptions,
  onSaveProject,
  onExportSrt,
  onExportVtt,
  onOpenProduction,
}: ToolbarProps) {
  const videoInputRef = useRef<HTMLInputElement>(null);
  const subtitleInputRef = useRef<HTMLInputElement>(null);

  return (
    <header className="toolbar">
      <div className="brand-lockup" aria-label="Caption Studio">
        <span className="brand-mark" aria-hidden="true">C</span>
        <strong>Caption Studio</strong>
      </div>

      <picture className="leo-studio-lockup" aria-label="Leo Studio">
        <source srcSet="/brand/leo-studio-light.png" media="(prefers-color-scheme: light)" />
        <img src="/brand/leo-studio-dark.png" alt="Leo Studio" />
      </picture>

      <div className="toolbar-actions">
        <input
          ref={videoInputRef}
          hidden
          type="file"
          accept="video/*"
          onChange={(event) => {
            const file = event.currentTarget.files?.[0];
            if (file) onOpenVideo(file);
            event.currentTarget.value = "";
          }}
        />
        <input
          ref={subtitleInputRef}
          hidden
          type="file"
          accept=".srt,.vtt,text/vtt,application/x-subrip"
          onChange={(event) => {
            const file = event.currentTarget.files?.[0];
            if (file) onImportCaptions(file);
            event.currentTarget.value = "";
          }}
        />

        <button className="button button-primary" onClick={() => videoInputRef.current?.click()}>
          <FolderOpen size={15} />
          영상 열기
        </button>
        <button className="button" onClick={() => subtitleInputRef.current?.click()}>
          <FileInput size={15} />
          SRT/VTT 가져오기
        </button>
        <span className="toolbar-divider" aria-hidden="true" />
        <button className="button automation-button" onClick={() => onOpenProduction("transcribe")}>
          <Mic2 size={15} />
          자동 자막
        </button>
        <button className="button automation-button" onClick={() => onOpenProduction("render")}>
          <Film size={15} />
          영상 출력
        </button>
        <span className="toolbar-divider" aria-hidden="true" />
        <button className="button" onClick={onSaveProject} title="프로젝트 JSON 저장 (⌘/Ctrl+S)">
          <Save size={15} />
          프로젝트 저장
        </button>
        <div className="export-group" aria-label="자막 내보내기">
          <button className="button" onClick={onExportSrt}>
            <Download size={15} />
            SRT 내보내기
          </button>
          <button className="button export-secondary" onClick={onExportVtt}>VTT</button>
        </div>
      </div>

      <div className={`save-state ${saveStatus}`} role="status">
        {saveStatus === "saved" ? <Check size={14} /> : <span className="save-spinner" />}
        {saveStatus === "saved" ? "저장됨" : "저장 중"}
      </div>
    </header>
  );
}
