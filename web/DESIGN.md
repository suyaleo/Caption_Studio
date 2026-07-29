# Caption Studio Design Contract

Reference: `../docs/design/caption-studio-concept.png`

## Layout

- Fixed desktop editor shell, optimized for 1440×900.
- 58px top toolbar.
- 300px subtitle rail, fluid preview canvas, 320px inspector.
- 218px timeline spanning the full width below the workspace.
- No page-level scrolling or marketing content.

## Tokens

- Background: `#111315`
- Panel: `#181b1d`
- Raised control: `#222527`
- Border: `#303437`
- Text: `#f3f1ed`
- Muted text: `#9ca1a5`
- Accent: `#ff783d`
- Radius: 6px controls, 8px panels
- Typography: Pretendard/system Korean UI stack, 12–14px chrome

## Visible Copy Lock

- Caption Studio
- wedding-film-01
- 영상 열기
- SRT/VTT 가져오기
- 자동 자막
- 영상 출력
- 프로젝트 저장
- SRT 내보내기
- VTT 내보내기
- 저장됨 / 저장 중
- 자막 목록
- 자막 편집
- 타임라인

## Component Families

- Flat toolbar actions with 1px border and quiet hover fill.
- Timestamped caption rows with an orange selected outline.
- Open video canvas with code-rendered subtitle overlay.
- Inspector groups separated by thin rules, not cards.
- Timeline track blocks with drag and edge-resize affordances.
- Right-edge production center with runtime readiness, model choice, progress, review, and download states.

## Production Workflow

- Browser-local video and subtitle editing are functional.
- The local Python job API owns media upload, mlx-whisper transcription, QA evidence, ASS generation, FFmpeg rendering, and MP4 download.
- Low-confidence ASR is surfaced for human review rather than hidden or silently approved.
