import {
  AlertTriangle,
  AlignCenter,
  AlignLeft,
  AlignRight,
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  RotateCcw,
} from "lucide-react";
import type { CaptionAlign, CaptionPosition, CaptionSegment, CaptionStyle } from "../features/captions/types";
import { CAPTION_FONTS, mergedStyle } from "../features/captions/types";
import { formatShortClock } from "../features/captions/time";

interface InspectorProps {
  selected?: CaptionSegment;
  globalStyle: CaptionStyle;
  onUpdateCaption: (id: string, patch: Partial<CaptionSegment>) => void;
  onUpdateStyle: (patch: Partial<CaptionStyle>) => void;
  onUpdateGlobalStyle: (patch: Partial<CaptionStyle>) => void;
}

function NumericField({
  label,
  value,
  onChange,
  step = 0.1,
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
  step?: number;
}) {
  return (
    <label className="field numeric-field">
      <span>{label}</span>
      <input
        type="number"
        min={0}
        step={step}
        value={Number(value.toFixed(3))}
        onChange={(event) => onChange(Number(event.currentTarget.value))}
      />
    </label>
  );
}

export function Inspector({
  selected,
  globalStyle,
  onUpdateCaption,
  onUpdateStyle,
  onUpdateGlobalStyle,
}: InspectorProps) {
  if (!selected) {
    return (
      <aside className="inspector panel">
        <div className="panel-heading"><div><h2>자막 편집</h2></div></div>
        <div className="inspector-empty">왼쪽 목록에서 자막을 선택하세요.</div>
      </aside>
    );
  }

  const style = mergedStyle(globalStyle, selected);

  return (
    <aside className="inspector panel">
      <div className="panel-heading inspector-heading">
        <div>
          <h2>자막 편집</h2>
          <span>{formatShortClock(selected.start)} — {formatShortClock(selected.end)}</span>
        </div>
      </div>

      <div className="inspector-scroll">
        <section className="inspector-section">
          {selected.confidence != null && selected.confidence < 0.6 ? (
            <div className="caption-review-callout">
              <AlertTriangle size={14} />
              <div>
                <strong>직접 확인이 필요한 자막</strong>
                <span>음성 인식 신뢰도 {Math.round(selected.confidence * 100)}% · 원본을 재생해 문구를 확인하세요.</span>
              </div>
            </div>
          ) : null}
          {selected.sourceText ? (
            <div className="source-caption-block">
              <span>인식된 원문</span>
              <p>{selected.sourceText}</p>
            </div>
          ) : null}
          <label className="field">
            <span>텍스트</span>
            <textarea
              value={selected.text}
              rows={4}
              onChange={(event) => onUpdateCaption(selected.id, { text: event.currentTarget.value })}
            />
          </label>
          <div className="field-grid">
            <NumericField label="시작 (초)" value={selected.start} onChange={(start) => onUpdateCaption(selected.id, { start })} />
            <NumericField label="종료 (초)" value={selected.end} onChange={(end) => onUpdateCaption(selected.id, { end })} />
          </div>
        </section>

        <section className="inspector-section">
          <div className="section-label-row">
            <h3>타이포그래피</h3>
            <button
              className="text-button"
              onClick={() => onUpdateCaption(selected.id, { styleOverride: undefined })}
            >
              기본값 복원
            </button>
          </div>
          <label className="field font-field">
            <span>폰트</span>
            <select
              value={style.fontFamily}
              style={{ fontFamily: `"${style.fontFamily}", sans-serif` }}
              onChange={(event) => onUpdateStyle({ fontFamily: event.currentTarget.value })}
            >
              {CAPTION_FONTS.map((font) => (
                <option key={font.value} value={font.value} style={{ fontFamily: font.value }}>{font.label}</option>
              ))}
            </select>
          </label>
          <div className="field-grid">
            <NumericField label="크기" value={style.fontSize} step={1} onChange={(fontSize) => onUpdateStyle({ fontSize })} />
            <label className="field color-field">
              <span>글자색</span>
              <span className="color-input-wrap">
                <input type="color" value={style.color} onChange={(event) => onUpdateStyle({ color: event.currentTarget.value })} />
                <code>{style.color.toUpperCase()}</code>
              </span>
            </label>
          </div>
          <div className="segmented-control" aria-label="자막 정렬">
            {([
              ["left", AlignLeft, "왼쪽"],
              ["center", AlignCenter, "가운데"],
              ["right", AlignRight, "오른쪽"],
            ] as const).map(([value, Icon, label]) => (
              <button
                key={value}
                className={style.align === value ? "active" : ""}
                onClick={() => onUpdateStyle({ align: value as CaptionAlign })}
                aria-label={`${label} 정렬`}
              >
                <Icon size={16} />
              </button>
            ))}
          </div>
        </section>

        <section className="inspector-section">
          <h3>가독성</h3>
          <label className="switch-row">
            <span>외곽선</span>
            <input
              type="checkbox"
              checked={style.outlineEnabled}
              onChange={(event) => onUpdateStyle({ outlineEnabled: event.currentTarget.checked })}
            />
          </label>
          {style.outlineEnabled && (
            <div className="field-grid compact-top">
              <label className="field color-field">
                <span>외곽선 색</span>
                <span className="color-input-wrap"><input type="color" value={style.outlineColor} onChange={(event) => onUpdateStyle({ outlineColor: event.currentTarget.value })} /><code>{style.outlineColor.toUpperCase()}</code></span>
              </label>
              <NumericField label="두께" value={style.outlineWidth} step={1} onChange={(outlineWidth) => onUpdateStyle({ outlineWidth })} />
            </div>
          )}
          <label className="switch-row">
            <span>자막 배경</span>
            <input
              type="checkbox"
              checked={style.backgroundEnabled}
              onChange={(event) => onUpdateStyle({ backgroundEnabled: event.currentTarget.checked })}
            />
          </label>
        </section>

        <section className="inspector-section">
          <h3>화면 위치</h3>
          <div className="position-grid" aria-label="자막 화면 위치">
            {(["top", "middle", "bottom"] as CaptionPosition[]).map((position) => (
              <button
                key={position}
                className={style.position === position ? "active" : ""}
                onClick={() => onUpdateStyle({ position })}
              >
                <span />
                {{ top: "상단", middle: "중앙", bottom: "하단" }[position]}
              </button>
            ))}
          </div>
          <div className="position-fine-tune">
            <div className="position-readout" aria-live="polite">
              <span>미세 조정</span>
              <code>X {signed(style.offsetX)} · Y {signed(style.offsetY)}</code>
            </div>
            <div className="position-dpad" aria-label="자막 위치 미세 조정">
              <button className="up" onClick={() => onUpdateStyle({ offsetY: clampOffset(style.offsetY - 24, 270) })} aria-label="자막 위로 이동"><ArrowUp size={15} /></button>
              <button className="left" onClick={() => onUpdateStyle({ offsetX: clampOffset(style.offsetX - 24, 480) })} aria-label="자막 왼쪽으로 이동"><ArrowLeft size={15} /></button>
              <button className="reset" onClick={() => onUpdateStyle({ offsetX: 0, offsetY: 0 })} aria-label="미세 조정 초기화" title="미세 조정 초기화"><RotateCcw size={13} /></button>
              <button className="right" onClick={() => onUpdateStyle({ offsetX: clampOffset(style.offsetX + 24, 480) })} aria-label="자막 오른쪽으로 이동"><ArrowRight size={15} /></button>
              <button className="down" onClick={() => onUpdateStyle({ offsetY: clampOffset(style.offsetY + 24, 270) })} aria-label="자막 아래로 이동"><ArrowDown size={15} /></button>
            </div>
            <p>한 번에 24px씩 이동하며 최종 영상에도 그대로 적용됩니다.</p>
          </div>
        </section>

        <section className="inspector-section global-style-section">
          <div>
            <h3>프로젝트 기본 스타일</h3>
            <p>새 자막과 스타일 재설정에 적용됩니다.</p>
          </div>
          <button
            className="button compact-button"
            onClick={() => onUpdateGlobalStyle(style)}
          >
            현재 스타일로 설정
          </button>
        </section>
      </div>
    </aside>
  );
}

function signed(value: number): string {
  return value > 0 ? `+${value}` : String(value);
}

function clampOffset(value: number, limit: number): number {
  return Math.max(-limit, Math.min(limit, value));
}
