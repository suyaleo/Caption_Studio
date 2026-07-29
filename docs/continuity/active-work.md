# Active Work

Caption Studio v0.5.1 unifies the existing React editor and Python media pipeline across three isolated runtime channels:

- macOS end-user installation in a dedicated `uv tool` environment with bundled Web assets;
- macOS native development in a repository `.venv` with mlx-whisper;
- Linux Docker deployment with faster-whisper CPU inference.

The public release contract includes Apache-2.0 licensing, runtime data isolation, Docker health checks, persistent storage, CI, GHCR publication and a clean public Git history.

Verification commands are maintained in the root README.
