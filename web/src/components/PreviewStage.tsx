import { Film } from "lucide-react";
import type { RefObject } from "react";
import type { CaptionSegment, CaptionStyle } from "../features/captions/types";
import { mergedStyle } from "../features/captions/types";

interface PreviewStageProps {
  videoRef: RefObject<HTMLVideoElement | null>;
  videoUrl: string | null;
  mediaName: string | null;
  activeCaption?: CaptionSegment;
  globalStyle: CaptionStyle;
  onTimeUpdate: (time: number) => void;
  onDuration: (duration: number) => void;
  onEnded: () => void;
}

export function PreviewStage({
  videoRef,
  videoUrl,
  mediaName,
  activeCaption,
  globalStyle,
  onTimeUpdate,
  onDuration,
  onEnded,
}: PreviewStageProps) {
  const style = mergedStyle(globalStyle, activeCaption);
  const positionClass = `position-${style.position}`;

  return (
    <main className="preview-workspace">
      <div className="workspace-titlebar">
        <div>
          <span className="eyebrow">미리보기</span>
          <strong>{mediaName ?? "샘플 영상 · 웨딩 인트로"}</strong>
        </div>
        <div className="resolution-badge">16:9 · FIT</div>
      </div>

      <div className="preview-surround">
        <div className="preview-frame">
          {videoUrl ? (
            <video
              ref={videoRef}
              src={videoUrl}
              playsInline
              preload="metadata"
              onTimeUpdate={(event) => onTimeUpdate(event.currentTarget.currentTime)}
              onLoadedMetadata={(event) => onDuration(event.currentTarget.duration)}
              onEnded={onEnded}
            />
          ) : (
            <img src="/assets/wedding-preview.png" alt="웨딩 영상 샘플 미리보기" />
          )}

          {activeCaption ? (
            <div className={`caption-overlay ${positionClass}`}>
              <span
                style={{
                  color: style.color,
                  fontFamily: `"${style.fontFamily}", sans-serif`,
                  fontSize: `${Math.max(18, style.fontSize * 0.62)}px`,
                  textAlign: style.align,
                  WebkitTextStroke: style.outlineEnabled
                    ? `${Math.max(1, style.outlineWidth * 0.65)}px ${style.outlineColor}`
                    : undefined,
                  background: style.backgroundEnabled ? style.backgroundColor : "transparent",
                  transform: `translate(${style.offsetX * 0.42}px, ${style.offsetY * 0.42}px)`,
                }}
              >
                {activeCaption.text}
              </span>
            </div>
          ) : null}

          {!videoUrl && (
            <div className="sample-media-label">
              <Film size={14} />
              영상 파일을 열면 이 샘플을 대체합니다
            </div>
          )}
        </div>
      </div>
    </main>
  );
}
