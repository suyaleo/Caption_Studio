"""CAT Artifact Bridge v1 companion endpoint for product-owned caption imports."""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from . import __version__
from .formats import cues_to_vtt
from .media_input import asr_provider_status, build_input_job_from_asr, probe_media, transcribe_audio
from .pipeline import segment_input_locally


PROTOCOL_VERSION = 1
ENGINE_ID = "caption-studio-bridge"
CAPABILITY = "generate-captions"
MEDIA_TYPE = "text/vtt"
PROMPT_MODE = "prompt-caption-v1"
ASR_MODE = "asr-v1"
CHECKPOINT_SCHEMA_VERSION = 1
_SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_LANGUAGE_PATTERN = re.compile(r"^(auto|[a-z]{2,3}(?:-[a-z0-9]{2,8})*)$")


class BridgeConflict(ValueError):
    """The caller reused an idempotency key for a different request."""


class CatArtifactBridge:
    """Materialize prompt or ASR VTT outputs with durable recovery checkpoints."""

    def __init__(
        self,
        workspace: Path,
        *,
        asr_transcriber: Callable[..., dict[str, Any]] | None = None,
        asr_status: Callable[..., dict[str, Any]] | None = None,
        media_prober: Callable[[Path], dict[str, Any]] | None = None,
    ) -> None:
        self.root = Path(workspace).resolve() / "cat-artifact-bridge-v1"
        self.operations_root = self.root / "operations"
        self.outputs_root = self.root / "outputs"
        self.operations_root.mkdir(parents=True, exist_ok=True)
        self.outputs_root.mkdir(parents=True, exist_ok=True)
        self._asr_transcriber = asr_transcriber or transcribe_audio
        self._asr_status = asr_status or asr_provider_status
        self._media_prober = media_prober or probe_media
        self._lock = threading.RLock()

    def health(self) -> dict[str, Any]:
        probe = self.root / ".health-write-probe"
        try:
            probe.write_bytes(b"ready")
            probe.unlink()
            ready = True
            message = "CAT Artifact Bridge v1 is ready"
        except OSError as exc:
            ready = False
            message = f"CAT Artifact Bridge workspace is not writable: {exc}"
        asr = self._asr_status()
        return {
            "ok": ready,
            "ready": ready,
            "protocolVersion": PROTOCOL_VERSION,
            "engineId": ENGINE_ID,
            "engineVersion": __version__,
            "capabilities": [CAPABILITY],
            "outputMediaTypes": [MEDIA_TYPE],
            "mode": "caption-bridge-v1",
            "modes": [PROMPT_MODE, ASR_MODE],
            "asr": asr,
            "recovery": {
                "intent": True,
                "partialSegments": True,
                "resultCheckpoint": True,
                "receipt": True,
            },
            "message": message,
        }

    def execute(self, request: dict[str, Any]) -> dict[str, Any]:
        normalized = _validate_request(request)
        key = normalized["idempotencyKey"]
        slug = hashlib.sha256(key.encode("utf-8")).hexdigest()
        fingerprint = _sha256_json(normalized)
        intent_path = self.operations_root / f"{slug}.intent.json"
        receipt_path = self.operations_root / f"{slug}.receipt.json"
        output_path = self.outputs_root / f"{slug}.vtt"

        with self._lock:
            if intent_path.is_file():
                intent = _read_json(intent_path)
                if intent.get("requestFingerprint") != fingerprint:
                    raise BridgeConflict("idempotency key was reused with a different request")
            else:
                _write_new_json(
                    intent_path,
                    {
                        "schemaVersion": 1,
                        "requestFingerprint": fingerprint,
                        "request": normalized,
                    },
                )

            if normalized["parameters"]["mode"] == ASR_MODE:
                vtt_bytes, provenance = self._render_asr_vtt(normalized, slug, fingerprint)
            else:
                vtt_bytes = _render_prompt_vtt(normalized)
                provenance = {
                    "mode": PROMPT_MODE,
                    "captionSource": "scene-script",
                    "language": normalized["parameters"]["language"],
                }
            expected_hash = _sha256_bytes(vtt_bytes)
            if output_path.is_file():
                actual_hash = _sha256_bytes(output_path.read_bytes())
                if actual_hash != expected_hash:
                    raise BridgeConflict("existing bridge output does not match the durable intent")
            else:
                _atomic_write(output_path, vtt_bytes)

            if receipt_path.is_file():
                receipt = _read_json(receipt_path)
                _validate_receipt(receipt, normalized, expected_hash, slug)
                return receipt

            response = {
                "protocolVersion": PROTOCOL_VERSION,
                "engineId": ENGINE_ID,
                "engineVersion": __version__,
                "idempotencyKey": key,
                "status": "complete",
                "output": {
                    "mediaType": MEDIA_TYPE,
                    "contentHash": expected_hash,
                    "downloadUrl": f"/cat/v1/outputs/{slug}.vtt",
                },
                "provenance": provenance,
            }
            _write_new_json(receipt_path, response)
            return response

    def output_path(self, filename: str) -> Path:
        if len(filename) != 68 or not filename.endswith(".vtt"):
            raise FileNotFoundError(filename)
        slug = filename[:-4]
        if len(slug) != 64 or any(character not in "0123456789abcdef" for character in slug):
            raise FileNotFoundError(filename)
        path = self.outputs_root / filename
        if not path.is_file():
            raise FileNotFoundError(filename)
        return path

    def _render_asr_vtt(
        self,
        request: dict[str, Any],
        slug: str,
        fingerprint: str,
    ) -> tuple[bytes, dict[str, Any]]:
        parameters = request["parameters"]
        source = _path_from_file_uri(request["inputPayloadUris"][0])
        actual_input_hash = _sha256_file(source)
        if actual_input_hash != parameters["inputContentHash"]:
            raise BridgeConflict(
                f"ASR input hash mismatch: expected {parameters['inputContentHash']}, got {actual_input_hash}"
            )

        partial_path = self.operations_root / f"{slug}.asr.partial.json"
        result_path = self.operations_root / f"{slug}.asr.complete.json"
        probe_path = self.operations_root / f"{slug}.probe.json"
        cues_path = self.operations_root / f"{slug}.cues.json"

        complete = _read_checkpoint(result_path, fingerprint) if result_path.is_file() else None
        recovered_from_partial = False
        if complete:
            asr_result = complete["result"]
            recovered_from_partial = bool(complete.get("partialCheckpointRecovered", False))
        else:
            partial = _read_checkpoint(partial_path, fingerprint) if partial_path.is_file() else None
            recovered_segments = _merge_asr_segments((partial or {}).get("segments", []))
            recovered_from_partial = bool(recovered_segments)
            resume_at = max((float(segment["end"]) for segment in recovered_segments), default=0.0)

            def on_segment(segment: dict[str, Any]) -> None:
                nonlocal recovered_segments
                recovered_segments = _merge_asr_segments([*recovered_segments, segment])
                _atomic_write_json(
                    partial_path,
                    {
                        "schemaVersion": CHECKPOINT_SCHEMA_VERSION,
                        "requestFingerprint": fingerprint,
                        "status": "partial",
                        "provider": parameters["provider"],
                        "model": parameters["model"],
                        "segments": recovered_segments,
                    },
                )

            asr_result = self._asr_transcriber(
                source,
                parameters["model"],
                language=None if parameters["language"] == "auto" else parameters["language"].split("-", 1)[0],
                provider=parameters["provider"],
                device=parameters["device"],
                compute_type=parameters["computeType"],
                word_timestamps=parameters["wordTimestamps"] == "true",
                clip_timestamps=f"{resume_at:.3f}" if resume_at > 0 else "0",
                on_segment=on_segment,
            )
            if not isinstance(asr_result, dict):
                raise RuntimeError("ASR provider returned an unsupported result")
            selected_provider = str(asr_result.get("_provider") or "")
            if selected_provider != parameters["provider"]:
                raise RuntimeError(
                    f"ASR provider mismatch: requested {parameters['provider']}, got {selected_provider or 'unknown'}"
                )
            asr_result = dict(asr_result)
            asr_result["segments"] = _merge_asr_segments(
                [*recovered_segments, *(asr_result.get("segments") or [])]
            )
            if not asr_result["segments"]:
                raise RuntimeError("ASR provider produced no usable speech segments")
            _atomic_write_json(
                result_path,
                {
                    "schemaVersion": CHECKPOINT_SCHEMA_VERSION,
                    "requestFingerprint": fingerprint,
                    "status": "complete",
                    "partialCheckpointRecovered": recovered_from_partial,
                    "result": asr_result,
                },
            )

        if str(asr_result.get("_provider") or "") != parameters["provider"]:
            raise BridgeConflict("ASR checkpoint provider does not match the durable request")

        if probe_path.is_file():
            probe = _read_checkpoint(probe_path, fingerprint)["probe"]
        else:
            probe = self._media_prober(source)
            _atomic_write_json(
                probe_path,
                {
                    "schemaVersion": CHECKPOINT_SCHEMA_VERSION,
                    "requestFingerprint": fingerprint,
                    "probe": probe,
                },
            )

        if cues_path.is_file():
            shifted_cues = _read_checkpoint(cues_path, fingerprint)["cues"]
        else:
            detected_language = str(asr_result.get("language") or parameters["language"])
            input_job = build_input_job_from_asr(
                media_path=source,
                asr_result=asr_result,
                media_probe=probe,
                job_id=request["idempotencyKey"],
                asr_model=parameters["model"],
                source_language=detected_language,
                target_language=detected_language,
            )
            local_cues = segment_input_locally(input_job).get("subtitle_cues", [])
            shifted_cues = _shift_cues(
                local_cues,
                start_ms=int(parameters["startMs"]),
                end_ms=int(parameters["endMs"]),
            )
            if not shifted_cues:
                raise RuntimeError("ASR result has no cues inside the selected Scene window")
            _atomic_write_json(
                cues_path,
                {
                    "schemaVersion": CHECKPOINT_SCHEMA_VERSION,
                    "requestFingerprint": fingerprint,
                    "cues": shifted_cues,
                },
            )

        value = cues_to_vtt(shifted_cues).encode("utf-8")
        return value, {
            "mode": ASR_MODE,
            "captionSource": "asr",
            "provider": parameters["provider"],
            "model": parameters["model"],
            "language": str(asr_result.get("language") or parameters["language"]),
            "device": parameters["device"],
            "computeType": parameters["computeType"],
            "wordTimestamps": parameters["wordTimestamps"] == "true",
            "inputContentHash": actual_input_hash,
            "partialCheckpointRecovered": recovered_from_partial,
        }


def _validate_request(request: dict[str, Any]) -> dict[str, Any]:
    if request.get("protocolVersion") != PROTOCOL_VERSION:
        raise ValueError(f"protocolVersion must be {PROTOCOL_VERSION}")
    if request.get("engineId") != ENGINE_ID:
        raise ValueError(f"engineId must be {ENGINE_ID}")
    if request.get("capability") != CAPABILITY:
        raise ValueError(f"capability must be {CAPABILITY}")
    idempotency_key = _required_string(request, "idempotencyKey", maximum=512)
    scene_id = _required_string(request, "sceneId", maximum=512)
    prompt = _required_string(request, "prompt", maximum=20_000)
    parent_artifact_id = _required_string(request, "parentArtifactId", maximum=512)
    raw_uris = request.get("inputPayloadUris")
    if not isinstance(raw_uris, list) or len(raw_uris) != 1 or not isinstance(raw_uris[0], str):
        raise ValueError("inputPayloadUris must contain exactly one local media URI")
    source = _path_from_file_uri(raw_uris[0])
    if not source.is_file():
        raise ValueError(f"input media does not exist: {source}")
    raw_parameters = request.get("parameters", {})
    if not isinstance(raw_parameters, dict) or any(not isinstance(key, str) for key in raw_parameters):
        raise ValueError("parameters must be an object")
    mode = _string_parameter(raw_parameters, "mode", default=PROMPT_MODE, maximum=64)
    if mode not in {PROMPT_MODE, ASR_MODE}:
        raise ValueError(f"parameters.mode must be {PROMPT_MODE} or {ASR_MODE}")
    caption_source = _string_parameter(
        raw_parameters,
        "captionSource",
        default="asr" if mode == ASR_MODE else "scene-script",
        maximum=64,
    )
    expected_source = "asr" if mode == ASR_MODE else "scene-script"
    if caption_source != expected_source:
        raise ValueError(f"parameters.captionSource must be {expected_source} for {mode}")
    if mode == PROMPT_MODE and ("-->" in prompt or "WEBVTT" in prompt.upper()):
        raise ValueError("prompt contains reserved WebVTT syntax")

    start_ms = _integer_parameter(raw_parameters, "startMs", default=0)
    end_ms = _integer_parameter(raw_parameters, "endMs", default=2_000)
    if start_ms < 0 or end_ms <= start_ms or end_ms > 86_400_000:
        raise ValueError("caption timing must satisfy 0 <= startMs < endMs <= 86400000")
    language = _string_parameter(raw_parameters, "language", default="ko", maximum=32).lower().replace("_", "-")
    if not _LANGUAGE_PATTERN.fullmatch(language):
        raise ValueError("parameters.language must be auto or a BCP-47-like language code")

    parameters = {str(key): str(value) for key, value in sorted(raw_parameters.items())}
    parameters.update(
        {
            "mode": mode,
            "captionSource": caption_source,
            "startMs": str(start_ms),
            "endMs": str(end_ms),
            "language": language,
        }
    )
    if mode == ASR_MODE:
        provider = _string_parameter(raw_parameters, "provider", default="", maximum=64).lower()
        provider = {"faster": "faster-whisper", "mlx": "mlx-whisper"}.get(provider, provider)
        if provider not in {"faster-whisper", "mlx-whisper"}:
            raise ValueError("parameters.provider must explicitly select faster-whisper or mlx-whisper")
        model = _string_parameter(raw_parameters, "model", default="", maximum=512)
        device = _string_parameter(
            raw_parameters,
            "device",
            default="mlx" if provider == "mlx-whisper" else "cpu",
            maximum=32,
        ).lower()
        allowed_devices = {"auto", "mlx"} if provider == "mlx-whisper" else {"auto", "cpu", "cuda"}
        if device not in allowed_devices:
            raise ValueError(f"parameters.device is not supported by {provider}")
        compute_type = _string_parameter(
            raw_parameters,
            "computeType",
            default="mlx-native" if provider == "mlx-whisper" else "int8",
            maximum=64,
        )
        word_timestamps = _boolean_parameter(raw_parameters, "wordTimestamps", default=True)
        input_hash = _string_parameter(raw_parameters, "inputContentHash", default="", maximum=80).lower()
        if not _SHA256_PATTERN.fullmatch(input_hash):
            raise ValueError("parameters.inputContentHash must be a sha256:<64 lowercase hex> digest")
        parameters.update(
            {
                "provider": provider,
                "model": model,
                "device": device,
                "computeType": compute_type,
                "wordTimestamps": "true" if word_timestamps else "false",
                "inputContentHash": input_hash,
            }
        )
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "engineId": ENGINE_ID,
        "idempotencyKey": idempotency_key,
        "capability": CAPABILITY,
        "sceneId": scene_id,
        "prompt": prompt,
        "parentArtifactId": parent_artifact_id,
        "inputPayloadUris": [raw_uris[0]],
        "parameters": parameters,
    }


def _render_prompt_vtt(request: dict[str, Any]) -> bytes:
    parameters = request["parameters"]
    text = request["prompt"].replace("\r\n", "\n").replace("\r", "\n").strip()
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    value = cues_to_vtt(
        [
            {
                "start_ms": int(parameters["startMs"]),
                "end_ms": int(parameters["endMs"]),
                "lines": lines,
            }
        ]
    )
    return value.encode("utf-8")


def _shift_cues(cues: list[dict[str, Any]], *, start_ms: int, end_ms: int) -> list[dict[str, Any]]:
    shifted: list[dict[str, Any]] = []
    for cue in cues:
        cue_start = start_ms + int(cue["start_ms"])
        cue_end = min(start_ms + int(cue["end_ms"]), end_ms)
        if cue_start >= end_ms or cue_end <= cue_start:
            continue
        shifted.append({**cue, "start_ms": cue_start, "end_ms": cue_end})
    return shifted


def _merge_asr_segments(segments: list[Any]) -> list[dict[str, Any]]:
    merged: dict[tuple[int, int, str], dict[str, Any]] = {}
    for raw in segments:
        if not isinstance(raw, dict):
            continue
        try:
            start = float(raw.get("start", 0.0))
            end = float(raw.get("end", 0.0))
        except (TypeError, ValueError):
            continue
        text = " ".join(str(raw.get("text", "")).split())
        if start < 0 or end <= start or not text:
            continue
        normalized = dict(raw)
        normalized.update({"start": start, "end": end, "text": text})
        merged[(round(start * 1000), round(end * 1000), text)] = normalized
    return sorted(merged.values(), key=lambda segment: (float(segment["start"]), float(segment["end"]), segment["text"]))


def _validate_receipt(
    receipt: dict[str, Any],
    request: dict[str, Any],
    expected_hash: str,
    slug: str,
) -> None:
    output = receipt.get("output")
    if (
        receipt.get("protocolVersion") != PROTOCOL_VERSION
        or receipt.get("engineId") != ENGINE_ID
        or receipt.get("idempotencyKey") != request["idempotencyKey"]
        or receipt.get("status") != "complete"
        or not isinstance(output, dict)
        or output.get("mediaType") != MEDIA_TYPE
        or output.get("contentHash") != expected_hash
        or output.get("downloadUrl") != f"/cat/v1/outputs/{slug}.vtt"
    ):
        raise BridgeConflict("existing bridge receipt does not match the durable output")


def _required_string(request: dict[str, Any], key: str, *, maximum: int) -> str:
    value = request.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    value = value.strip()
    if len(value) > maximum:
        raise ValueError(f"{key} exceeds {maximum} characters")
    return value


def _string_parameter(parameters: dict[str, Any], key: str, *, default: str, maximum: int) -> str:
    value = parameters.get(key, default)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"parameters.{key} must be a non-empty string")
    value = value.strip()
    if len(value) > maximum:
        raise ValueError(f"parameters.{key} exceeds {maximum} characters")
    return value


def _integer_parameter(parameters: dict[str, Any], key: str, *, default: int) -> int:
    value = parameters.get(key, default)
    if isinstance(value, bool):
        raise ValueError(f"parameters.{key} must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"parameters.{key} must be an integer") from exc


def _boolean_parameter(parameters: dict[str, Any], key: str, *, default: bool) -> bool:
    value = parameters.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in {"true", "false"}:
        return value.strip().lower() == "true"
    raise ValueError(f"parameters.{key} must be true or false")


def _path_from_file_uri(value: str) -> Path:
    parsed = urlparse(value)
    if parsed.scheme != "file" or parsed.netloc not in {"", "localhost"}:
        raise ValueError("input payload must use a local file URI")
    raw = unquote(parsed.path)
    if os.name == "nt" and len(raw) >= 3 and raw[0] == "/" and raw[2] == ":":
        raw = raw[1:]
    return Path(raw).resolve()


def _sha256_json(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _sha256_bytes(payload)


def _sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"invalid bridge record: {path.name}")
    return payload


def _read_checkpoint(path: Path, fingerprint: str) -> dict[str, Any]:
    payload = _read_json(path)
    if (
        payload.get("schemaVersion") != CHECKPOINT_SCHEMA_VERSION
        or payload.get("requestFingerprint") != fingerprint
    ):
        raise BridgeConflict(f"checkpoint does not match the durable ASR request: {path.name}")
    return payload


def _write_new_json(path: Path, value: dict[str, Any]) -> None:
    payload = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    try:
        with path.open("xb") as destination:
            destination.write(payload)
            destination.flush()
            os.fsync(destination.fileno())
    except FileExistsError:
        raise BridgeConflict(f"bridge record already exists: {path.name}") from None


def _atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    payload = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    _atomic_write(path, payload)


def _atomic_write(path: Path, payload: bytes) -> None:
    pending = path.with_name(f".{path.name}.pending")
    with pending.open("wb") as destination:
        destination.write(payload)
        destination.flush()
        os.fsync(destination.fileno())
    os.replace(pending, path)
