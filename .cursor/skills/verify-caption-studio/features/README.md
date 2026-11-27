# Caption Studio feature map

| Feature | File | Primary drive |
|---|---|---|
| Subtitle export (SRT/VTT/ASS) — CLI and web toolbar | [subtitle-export.md](subtitle-export.md) | `verify.sh cli-export <fmt>`, `verify.sh web-export <fmt>` |
| Subtitle import (SRT/VTT) in the web editor | [subtitle-import.md](subtitle-import.md) | vitest `formats.test.ts`; manual CDP file input |
| Local CLI pipeline (segment-local, validate, run-all) | [cli-pipeline.md](cli-pipeline.md) | `uv run subtitle-automation ...` |
| Production panel: auto-transcribe and hard-sub render | [production-jobs.md](production-jobs.md) | `scripts/docker_smoke_test.sh`, `/api/jobs/*` |
