---
name: verify-caption-studio
description: Verify Caption Studio (suyaleo/Caption_Studio) end to end — the CI-equivalent suite (release validation, Python unittest + pytest, web typecheck/vitest/build, static-asset sync, uv tool install, optional Docker job), the `subtitle-automation` CLI export path on examples/demo_input.json, and the packaged web UI export buttons driven in headless Chromium. Use before claiming any Caption Studio change works, and after touching formats, CLI, web toolbar, or the packaged static build.
---

# Verify Caption Studio

Surfaces: **CLI** `subtitle-automation` (primary for format work), **web UI** (React app in `web/`, packaged into `src/subtitle_automation/static/` and served by `caption-studio`), **HTTP API** (`/api/health`, `/api/media`, `/api/jobs/*` in `web_server.py`). Everything goes through one helper:

```bash
H=.cursor/skills/verify-caption-studio/scripts/verify.sh
$H doctor            # read-only: tools, branch/HEAD, version, packaged static present
$H suite             # CI "application" job mirror + pytest (≈1–2 min)
$H cli-export ass    # demo_input.json -> segment-local -> format-ass, structural check
$H web-export ass    # packaged server + headless chromium clicks the ASS button
$H all ass           # doctor + suite + cli-export + web-export
$H ci                # suite + CI "docker" job (needs docker daemon; slow)
$H cleanup           # stop only servers/browsers this helper started
```

Format argument is `srt`, `vtt` or `ass`. Evidence goes to `/tmp/caption-studio-verify/<run-id>/` (override root with `CAPTION_STUDIO_VERIFY_EVIDENCE`, id with `CAPTION_STUDIO_VERIFY_RUN`). Run commands from the repo root on a host with `uv`, `node`/`npm`, and `chromium` (the n100 dev host has all three via mise and `/usr/bin/chromium`).

## Launch

- **CLI / suite:** no server. `uv sync --locked` (done by `suite`) and `cd web && npm ci`. Short-lived processes; each step's transcript is its own log file.
- **Web UI:** `web-export` picks a free port, runs `uv run caption-studio --host 127.0.0.1 --port <free> --workspace <scratch>/workspace` (serves the *packaged* static dir) and waits until `GET /api/health` answers. Ready = health JSON written to evidence **and** the export button is found in the DOM. The packaged static dir only reflects `web/src` after `npm run build` (run `suite` or `cd web && npm run build` first); CI fails if the rebuilt static differs from what is committed, so commit the rebuilt `src/subtitle_automation/static/` with any UI change.
- Isolation: each run uses its own port, workspace and Chromium profile, so parallel runs are safe. It never touches a running dev server on 8788 or the Docker deployment on 8768.

## Doctor

`$H doctor` — exits non-zero if `uv/node/npm/git` are missing or the packaged `static/index.html` is absent. It prints node version: CI pins **22.23.2**; a different local node is fine for tests, but if `static-in-sync` fails only locally, compare node/vite versions before blaming the change.

## Drive

- CLI: `uv run subtitle-automation segment-local --input examples/demo_input.json --output cues.json`, then `format-srt | format-vtt | format-ass --input cues.json --output out.<ext>`. `examples/demo_input.json` holds `input_segments` (ASR), not cues — the `format-*` commands need `subtitle_cues`/`cues`, hence the `segment-local` step. `run-all --input ... --output-dir ...` writes `subtitles/output.srt` and `output.vtt` (not ASS).
- Web: `scripts/web_export.mjs <url> <fmt> <evidence> <profile>` speaks raw CDP (node ≥22 global WebSocket, no npm deps). Handles: toolbar group `[aria-label="자막 내보내기"]`, buttons by text `SRT 내보내기`, `VTT`, `ASS`. Downloads land in `<evidence>/web-download/` with the app's filename (`<projectName>.<ext>`, default project `wedding-film-01` with the 6 `SEED_CAPTIONS` from `web/src/features/captions/types.ts` on a fresh profile).
- `scripts/check_subtitle.py <fmt> <file>` checks structure: VTT `WEBVTT` header + `HH:MM:SS.mmm --> HH:MM:SS.mmm`; SRT `HH:MM:SS,mmm`; ASS `[Script Info]`/`ScriptType: v4.00+`/`[V4+ Styles]`/`[Events]`, `Dialogue: 0,H:MM:SS.cc,H:MM:SS.cc,CaptionN,...`, one `Style: CaptionN` per dialogue.

## Evidence

Per run: `verify.log` (PASS/FAIL per step), one `<step>.log` transcript per suite step, `demo_cues.json` + `demo.<fmt>` (CLI output), `cli-check-<fmt>.txt`, `health.json`, `server.log`, `web-toolbar.png`, `web-download/<file>`, `web-check-<fmt>.txt`.
Proof standards: drive the real entry point (CLI subcommand, real button click, real download), not internal functions; check the file written, not just exit code; a format claim needs the structural check plus a look at the first lines. Unit tests (`tests/`, `web/src/**/*.test.ts`) complement but do not replace the drives.

## Cleanup

`web-export` cleans up after itself; `$H cleanup` removes any leftover `/tmp/caption-studio-verify/.scratch-*` after killing only the PIDs recorded there. Evidence directories are never deleted by cleanup.

Exit status: every `suite`/`ci` step runs even after a failure; the last log line is `RESULT: PASS` or `RESULT: FAIL (<steps>)` and the exit code is non-zero on any failure. `static-in-sync` compares against the committed tree exactly like CI, so commit the rebuilt `src/subtitle_automation/static/` before running `suite` (an uncommitted UI change correctly fails it). Never `pkill chromium`/`caption-studio` by name — the host runs other services.

## Feature map

See [features/README.md](features/README.md). Keep it current with `/maintain-verification-skill`.
