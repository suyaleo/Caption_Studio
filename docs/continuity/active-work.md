# Active Work

Caption Studio v0.5.1 unifies the existing React editor and Python media pipeline across three isolated runtime channels:

- macOS end-user installation in a dedicated `uv tool` environment with bundled Web assets;
- macOS native development in a repository `.venv` with mlx-whisper;
- Linux Docker deployment with faster-whisper CPU inference.

The public release contract includes Apache-2.0 licensing, runtime data isolation, Docker health checks, persistent storage, CI, GHCR publication and a clean public Git history.

The pushed integration checkpoint `002156a` on `codex/cat-artifact-bridge-v1` adds CAT Artifact Bridge v1 beside the existing server:

- `GET /cat/v1/health`, `POST /cat/v1/artifacts`, and same-origin VTT download;
- persistent intent/output/receipt with idempotent retry, restart reuse, conflict detection, and tamper rejection;
- deterministic `prompt-caption-v1` timing/text output for Creative Automation Tool contract acceptance;
- no change to the existing editor, ASR, translation, render, or Docker authority.

The focused Bridge/Web server suite passes 15 tests on Windows using the repository's bundled Python environment. The broader historical Windows suite still has pre-existing POSIX-path assertions and a hard-subprocess hang; do not report the full public release matrix as passing from this Windows checkpoint alone.

Verification commands are maintained in the root README.
