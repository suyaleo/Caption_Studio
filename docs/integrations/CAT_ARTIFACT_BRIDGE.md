# CAT Artifact Bridge v1

This companion API lets Creative Automation Tool request immutable CaptionTrack VTT output without embedding Caption Studio's UI, browser state, or project database. Caption Studio owns provider execution evidence; the host owns durable product Job state, final Artifact identity, approvals, rendering, and Delivery.

## Endpoints

- `GET /cat/v1/health` reports protocol/engine identity, supported modes, ASR provider availability, and checkpoint capabilities.
- `POST /cat/v1/artifacts` accepts one idempotent Caption request.
- `GET /cat/v1/outputs/{sha256}.vtt` serves the exact same-origin result named by its digest.

## Modes

### `prompt-caption-v1`

This deterministic proof mode converts the supplied prompt and `startMs`/`endMs` Scene window into VTT. It is useful for contract tests and is never an ASR fallback.

### `asr-v1`

The request must explicitly include:

- `captionSource=asr` and `mode=asr-v1`;
- provider `faster-whisper` or `mlx-whisper`;
- model, language, device, compute type, and `wordTimestamps`;
- the currently approved product-owned VoiceTrack URI and exact `inputContentHash`;
- Scene `startMs`/`endMs` and the owning `voiceRevisionId`.

Provider/device combinations are validated before execution. faster-whisper supports `cpu | cuda | auto`; MLX Whisper requires `mlx`. An unavailable provider is a health/configuration failure, not permission to select another runtime.

## Durable execution

One request fingerprint and idempotency key own the following atomic files:

1. intent;
2. partial ASR segments;
3. complete provider evidence;
4. normalized cues;
5. VTT output;
6. receipt.

The Bridge verifies the input audio hash before calling the provider. Each completed provider segment advances the partial checkpoint. After interruption, the same request resumes at the maximum durable segment end via the provider clip window, merges and deduplicates prior/new evidence, clips cues to the Scene window, and returns one logical output. A different request under the same key, a changed input hash, or tampered output/checkpoint is rejected.

## Receipt provenance

The receipt records mode, caption source, provider, model, language, device, compute type, word timestamp choice, input hash, Scene window, and whether partial recovery was used. It contains no credential. Creative Automation Tool must still download, size-check, and independently SHA-256 verify the VTT before copying it into its owned Artifact Store.

## Windows QA checkpoint

The non-release Windows QA path uses an isolated faster-whisper 1.2.1 runtime, `tiny`, English, CPU/int8, and real FFmpeg `flite` speech. The passing host E2E is `D:\Projects\creative_automation_tool\qa\native-e2e\windows-2026-08-20T051150-986Z`. This proves the contract and evidence chain; it does not define a bundled model runtime or final multilingual quality bar.
