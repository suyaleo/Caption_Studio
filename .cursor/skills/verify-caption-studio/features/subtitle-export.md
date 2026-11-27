# Subtitle export (SRT / VTT / ASS)

## Sub-features
- CLI `format-srt`, `format-vtt`, `format-ass` (`src/subtitle_automation/cli.py` → `formats.py`; ASS delegates to `rendering.captions_to_ass`, default style, 1920×1080).
- Web toolbar export group: `SRT 내보내기`, `VTT`, `ASS` (`web/src/components/Toolbar.tsx`, serializers in `web/src/features/captions/formats.ts`; web ASS uses the editor's global style + per-caption overrides).

## How to get to it (user POV)
- CLI: produce cue JSON (`segment-local` from a job like `examples/demo_input.json`), then `subtitle-automation format-ass --input cues.json --output out.ass`.
- Web: open Caption Studio, top-right toolbar → `ASS` (next to `VTT`) → browser downloads `<projectName>.ass`.

## Driving it with verify.sh
- `verify.sh cli-export ass` → `demo.ass` + `cli-check-ass.txt` must say `OK` with `cues=3` for the demo input.
- `verify.sh web-export ass` → `web-download/wedding-film-01.ass`, `web-check-ass.txt` `OK` with `cues=6` on a fresh profile; `web-toolbar.png` shows the button.
- Same for `vtt` (expect `WEBVTT` + `HH:MM:SS.mmm -->`) and `srt`.

## Gotchas
- `format-*` rejects `examples/demo_input.json` directly (no `subtitle_cues`); run `segment-local` first.
- ASS timestamps are centiseconds (`H:MM:SS.cc`), unlike SRT/VTT milliseconds.
- Web changes are only visible to the packaged server after `npm run build`; commit the regenerated `src/subtitle_automation/static/` or CI's static-sync step fails.
