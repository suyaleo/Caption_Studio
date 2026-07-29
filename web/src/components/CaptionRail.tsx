import { AlertTriangle, Plus, Trash2 } from "lucide-react";
import type { CaptionSegment } from "../features/captions/types";
import { formatShortClock } from "../features/captions/time";

interface CaptionRailProps {
  captions: CaptionSegment[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onAdd: () => void;
  onDelete: () => void;
}

export function CaptionRail({
  captions,
  selectedId,
  onSelect,
  onAdd,
  onDelete,
}: CaptionRailProps) {
  return (
    <aside className="caption-rail panel">
      <div className="panel-heading">
        <div>
          <h2>자막 목록</h2>
          <span>{captions.length}개 구간</span>
        </div>
        <div className="icon-actions">
          <button className="icon-button" onClick={onAdd} aria-label="현재 위치에 자막 추가" title="자막 추가">
            <Plus size={17} />
          </button>
          <button
            className="icon-button danger-hover"
            onClick={onDelete}
            aria-label="선택한 자막 삭제"
            title="선택 삭제"
            disabled={!selectedId}
          >
            <Trash2 size={16} />
          </button>
        </div>
      </div>

      <div className="caption-list" role="listbox" aria-label="자막 구간">
        {captions.length === 0 ? (
          <div className="empty-list">
            <p>아직 자막이 없습니다.</p>
            <button className="text-button" onClick={onAdd}>첫 자막 추가</button>
          </div>
        ) : captions.map((caption, index) => (
          <button
            className={`caption-row ${caption.id === selectedId ? "selected" : ""}`}
            key={caption.id}
            onClick={() => onSelect(caption.id)}
            role="option"
            aria-selected={caption.id === selectedId}
          >
            <span className="caption-index">{String(index + 1).padStart(2, "0")}</span>
            <span className="caption-row-content">
              <span className="caption-time">
                {formatShortClock(caption.start)} — {formatShortClock(caption.end)}
                {caption.confidence != null && caption.confidence < 0.6 ? (
                  <span className="caption-review-mark" title={`음성 인식 신뢰도 ${Math.round(caption.confidence * 100)}%`}>
                    <AlertTriangle size={9} /> 검토
                  </span>
                ) : null}
              </span>
              <span className="caption-copy">{caption.text}</span>
            </span>
          </button>
        ))}
      </div>
    </aside>
  );
}
