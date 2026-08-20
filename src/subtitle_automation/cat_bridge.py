"""CAT Artifact Bridge v1 companion endpoint for product-owned caption imports."""

from __future__ import annotations

import hashlib
import json
import os
import threading
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from . import __version__
from .formats import cues_to_vtt


PROTOCOL_VERSION = 1
ENGINE_ID = "caption-studio-bridge"
CAPABILITY = "generate-captions"
MEDIA_TYPE = "text/vtt"


class BridgeConflict(ValueError):
    """The caller reused an idempotency key for a different request."""


class CatArtifactBridge:
    """Materialize deterministic VTT outputs with crash-safe idempotency receipts."""

    def __init__(self, workspace: Path) -> None:
        self.root = Path(workspace).resolve() / "cat-artifact-bridge-v1"
        self.operations_root = self.root / "operations"
        self.outputs_root = self.root / "outputs"
        self.operations_root.mkdir(parents=True, exist_ok=True)
        self.outputs_root.mkdir(parents=True, exist_ok=True)
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
        return {
            "ok": ready,
            "ready": ready,
            "protocolVersion": PROTOCOL_VERSION,
            "engineId": ENGINE_ID,
            "engineVersion": __version__,
            "capabilities": [CAPABILITY],
            "outputMediaTypes": [MEDIA_TYPE],
            "mode": "prompt-caption-v1",
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

            vtt_bytes = _render_vtt(normalized)
            expected_hash = _sha256_bytes(vtt_bytes)
            if output_path.is_file():
                actual_hash = _sha256_bytes(output_path.read_bytes())
                if actual_hash != expected_hash:
                    raise BridgeConflict("existing bridge output does not match the durable intent")
            else:
                _atomic_write(output_path, vtt_bytes)

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
            }
            if receipt_path.is_file():
                receipt = _read_json(receipt_path)
                if receipt != response:
                    raise BridgeConflict("existing bridge receipt does not match the durable output")
            else:
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
    if "-->" in prompt or "WEBVTT" in prompt.upper():
        raise ValueError("prompt contains reserved WebVTT syntax")
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
    start_ms = _integer_parameter(raw_parameters, "startMs", default=0)
    end_ms = _integer_parameter(raw_parameters, "endMs", default=2_000)
    if start_ms < 0 or end_ms <= start_ms or end_ms > 86_400_000:
        raise ValueError("caption timing must satisfy 0 <= startMs < endMs <= 86400000")
    parameters = {str(key): str(value) for key, value in sorted(raw_parameters.items())}
    parameters["startMs"] = str(start_ms)
    parameters["endMs"] = str(end_ms)
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


def _render_vtt(request: dict[str, Any]) -> bytes:
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


def _required_string(request: dict[str, Any], key: str, *, maximum: int) -> str:
    value = request.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    value = value.strip()
    if len(value) > maximum:
        raise ValueError(f"{key} exceeds {maximum} characters")
    return value


def _integer_parameter(parameters: dict[str, Any], key: str, *, default: int) -> int:
    value = parameters.get(key, default)
    if isinstance(value, bool):
        raise ValueError(f"parameters.{key} must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"parameters.{key} must be an integer") from exc


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


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"invalid bridge record: {path.name}")
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


def _atomic_write(path: Path, payload: bytes) -> None:
    pending = path.with_name(f".{path.name}.pending")
    with pending.open("wb") as destination:
        destination.write(payload)
        destination.flush()
        os.fsync(destination.fileno())
    os.replace(pending, path)
