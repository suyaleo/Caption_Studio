# Production panel: auto-transcribe and render

## Sub-features
- Toolbar `자동 자막` (transcribe job) and `영상 출력` (hard-sub MP4 via FFmpeg + libass), API `/api/media`, `/api/jobs/transcribe`, `/api/jobs/render`, status via `/api/health`.

## How to get to it (user POV)
- Open a video, toolbar → `자동 자막` or `영상 출력`, follow the production panel.

## Driving it with verify.sh
- `verify.sh ci` runs `scripts/docker_smoke_test.sh` (persistent upload + hard-sub render in the Docker image).
- Health only: `curl http://127.0.0.1:<port>/api/health` from a `web-export` style server (`ffmpeg_ass`, ASR availability).

## Gotchas
- Needs ASR models (faster-whisper/mlx-whisper) and an FFmpeg with libass; on a fresh host `/api/health` reports `ok: false` and transcribe cannot be proven — report it, don't skip silently.
