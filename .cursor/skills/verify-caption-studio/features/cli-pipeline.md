# Local CLI pipeline

## Sub-features
- `segment-local`, `validate`, `render-prompt`, `llm-stage`, `run-all`, `prepare-mp4-input`, `run-media` (see `subtitle-automation --help`).

## How to get to it (user POV)
- `uv run subtitle-automation run-all --input examples/demo_input.json --output-dir out/` (no LLM configured → local fallback).

## Driving it with verify.sh
- `verify.sh cli-export <fmt>` covers `segment-local` + `format-*`.
- For `run-all`, check `out/subtitles/output.srt`, `output.vtt` and the manifest exist; `tests/test_cli.py` covers this offline.

## Gotchas
- `llm-stage`/translation need an OpenAI-compatible endpoint or provider OAuth; do not run them against real providers in verification without the user's approval.
