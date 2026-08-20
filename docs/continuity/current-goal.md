# Current Goal

Maintain Caption Studio as a usable local-first application that carries a user from video import through subtitle creation, review, styling and MP4 output.

Required properties:

- evidence and low-confidence warnings remain visible;
- Web and Docker use the same implementation;
- optional translation outages do not disable editing, transcription or rendering;
- working media and model caches remain outside Git;
- every public release passes Python, Web, Docker and manifest validation.
- CAT Artifact Bridge modes remain isolated from the editor authority, hash-verified, explicitly provider-selected, idempotent, and restart-recoverable.
