# Subtitle import (SRT / VTT)

## Sub-features
- Toolbar `SRT/VTT 가져오기` hidden file input (`accept=".srt,.vtt,..."`), parsed by `parseCaptionText` in `web/src/features/captions/formats.ts`.

## How to get to it (user POV)
- Toolbar → `SRT/VTT 가져오기` → choose a file → toast `N개 자막을 가져왔습니다.` and the caption rail (`role="listbox"`, `aria-label="자막 구간"`) shows the cues.

## Driving it with verify.sh
- Unit level: `cd web && npm test` (`formats.test.ts` parse + roundtrip cases).
- UI level (not yet scripted): with the `web_export.mjs` CDP session, use `DOM.setFileInputFiles` on `input[accept^=".srt"]` with an SRT from `verify.sh cli-export srt`, then count `[aria-label="자막 구간"] .caption-row`.

## Gotchas
- ASS import is not supported; only SRT/VTT parse.
