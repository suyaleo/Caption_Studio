"""Build subtitle input jobs from media-derived ASR evidence."""

from __future__ import annotations

import importlib.util
import json
import math
import os
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any


DEFAULT_POLICIES = {
    "clean_reading_mode": True,
    "redaction_mode": "flag_only",
    "profanity_mode": "preserve",
    "max_chars_per_line": 16,
    "max_lines_per_cue": 2,
    "max_cps": 15,
    "allow_overlap": False,
}

ASR_MODEL_ALIASES = {
    "mlx-community/whisper-small": "mlx-community/whisper-small-mlx",
}


def normalize_asr_model(asr_model: str) -> str:
    """Return the current public repository name for an ASR model preset."""

    return ASR_MODEL_ALIASES.get(asr_model, asr_model)


def faster_whisper_model_name(asr_model: str) -> str:
    """Map the UI's MLX model presets to faster-whisper model identifiers."""

    normalized = normalize_asr_model(asr_model).lower()
    if "large-v3-turbo" in normalized:
        return "turbo"
    for size in ("tiny", "base", "small", "medium", "large-v3"):
        if f"whisper-{size}" in normalized or normalized == size:
            return size
    return asr_model


def asr_provider_status() -> dict[str, Any]:
    """Describe the selected cross-platform ASR runtime without loading a model."""

    configured = os.getenv("CAPTION_ASR_PROVIDER", "auto").strip().lower()
    installed = {
        "mlx-whisper": importlib.util.find_spec("mlx_whisper") is not None,
        "faster-whisper": importlib.util.find_spec("faster_whisper") is not None,
    }
    provider = _select_asr_provider(configured, installed)
    return {
        "available": provider is not None,
        "provider": provider,
        "configured": configured,
        "installed": installed,
        "error": None if provider else _asr_unavailable_message(configured),
    }


def build_input_job_from_asr(
    *,
    media_path: Path,
    asr_result: dict[str, Any],
    media_probe: dict[str, Any],
    job_id: str,
    asr_model: str,
    source_language: str = "ko-KR",
    target_language: str = "ko-KR",
    policies: dict[str, Any] | None = None,
    confidence_threshold: float = 0.6,
) -> dict[str, Any]:
    """Convert Whisper-style ASR output into the existing run-all input contract."""

    asr_model = normalize_asr_model(asr_model)

    segments = [segment for segment in (asr_result.get("segments") or []) if _is_usable_asr_segment(segment)]
    if not segments:
        raise ValueError("ASR result must contain at least one usable segment")

    input_segments = [
        _segment_to_input_segment(index, segment, asr_model, confidence_threshold)
        for index, segment in enumerate(segments, start=1)
    ]

    return {
        "job_id": job_id,
        "ui_language": "ko-KR",
        "source_language_hint": source_language,
        "target_language": target_language,
        "source_media": _source_media(
            media_path,
            media_probe,
            asr_model,
            str(asr_result.get("_provider") or "whisper-compatible"),
        ),
        "content_profile": {
            "single_speaker": True,
            "multi_speaker": False,
            "noisy_audio": False,
            "music_background": False,
            "code_switching": False,
            "clip_length_seconds": _duration_seconds(media_probe),
        },
        "policies": {**DEFAULT_POLICIES, **(policies or {})},
        "reference_rules": (
            "Media-derived ASR evidence. Preserve uncertainty and do not invent speech beyond input_segments."
        ),
        "input_segments": input_segments,
    }


def prepare_media_input_job(
    *,
    media_path: Path,
    job_id: str,
    asr_model: str,
    source_language: str = "ko-KR",
    target_language: str = "ko-KR",
    policies: dict[str, Any] | None = None,
    work_dir: Path | None = None,
    asr_json_path: Path | None = None,
    media_probe_json_path: Path | None = None,
    raw_asr_output: Path | None = None,
    media_probe_output: Path | None = None,
    audio_output: Path | None = None,
) -> dict[str, Any]:
    """Prepare a run-all input job from an MP4 and optional cached evidence."""

    asr_model = normalize_asr_model(asr_model)
    media_path = Path(media_path)
    if not media_path.exists():
        raise FileNotFoundError(f"media file not found: {media_path}")

    if media_probe_json_path:
        media_probe = _read_json(media_probe_json_path)
    else:
        media_probe = probe_media(media_path)
    if media_probe_output:
        _write_json(media_probe_output, media_probe)

    if asr_json_path:
        asr_result = _read_json(asr_json_path)
    else:
        audio_path = audio_output or _default_audio_path(media_path, work_dir)
        extract_audio(media_path, audio_path)
        asr_result = transcribe_audio(audio_path, asr_model, language=_whisper_language(source_language))
    if raw_asr_output:
        _write_json(raw_asr_output, asr_result)

    return build_input_job_from_asr(
        media_path=media_path,
        asr_result=asr_result,
        media_probe=media_probe,
        job_id=job_id,
        asr_model=asr_model,
        source_language=source_language,
        target_language=target_language,
        policies=policies,
    )


def probe_media(media_path: Path) -> dict[str, Any]:
    """Run ffprobe and return media stream/format evidence as JSON."""

    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration,size:stream=index,codec_type,codec_name,width,height,duration",
        "-of",
        "json",
        str(media_path),
    ]
    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {media_path}: {completed.stderr.strip()}")
    return json.loads(completed.stdout)


def extract_audio(media_path: Path, audio_output: Path) -> Path:
    """Extract 16 kHz mono WAV audio suitable for Whisper-style ASR."""

    audio_output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(media_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        str(audio_output),
    ]
    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"ffmpeg audio extraction failed for {media_path}: {completed.stderr.strip()}")
    return audio_output


def transcribe_audio(audio_path: Path, asr_model: str, *, language: str | None = None) -> dict[str, Any]:
    """Run the configured macOS or Docker ASR provider."""

    asr_model = normalize_asr_model(asr_model)
    status = asr_provider_status()
    provider = status["provider"]
    if provider == "mlx-whisper":
        result = _transcribe_with_mlx(audio_path, asr_model, language=language)
    elif provider == "faster-whisper":
        result = _transcribe_with_faster_whisper(audio_path, asr_model, language=language)
    else:
        raise RuntimeError(str(status["error"]))
    result.setdefault("_provider", provider)
    return result


def _transcribe_with_mlx(audio_path: Path, asr_model: str, *, language: str | None) -> dict[str, Any]:
    """Run Apple Silicon native mlx-whisper."""

    try:
        import mlx_whisper  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - depends on local workstation install.
        raise RuntimeError("mlx-whisper is required unless --asr-json is provided") from exc

    try:
        result = mlx_whisper.transcribe(str(audio_path), path_or_hf_repo=asr_model, language=language)
    except TypeError:
        result = mlx_whisper.transcribe(str(audio_path), asr_model, language=language)
    if not isinstance(result, dict):
        raise RuntimeError("mlx-whisper returned an unsupported transcript payload")
    return result


def _transcribe_with_faster_whisper(audio_path: Path, asr_model: str, *, language: str | None) -> dict[str, Any]:
    """Run the Linux/Docker CPU provider and normalize its result to Whisper JSON."""

    model_name = faster_whisper_model_name(asr_model)
    model = _faster_whisper_model(
        model_name,
        os.getenv("CAPTION_ASR_DEVICE", "cpu"),
        os.getenv("CAPTION_ASR_COMPUTE_TYPE", "int8"),
        os.getenv("CAPTION_ASR_DOWNLOAD_ROOT") or None,
    )
    segments, info = model.transcribe(
        str(audio_path),
        language=language,
        vad_filter=True,
        beam_size=max(1, int(os.getenv("CAPTION_ASR_BEAM_SIZE", "5"))),
    )
    normalized_segments = [
        {
            "id": index,
            "start": float(segment.start),
            "end": float(segment.end),
            "text": str(segment.text),
            "avg_logprob": float(getattr(segment, "avg_logprob", -10.0)),
            "no_speech_prob": float(getattr(segment, "no_speech_prob", 0.0)),
        }
        for index, segment in enumerate(segments)
    ]
    return {
        "text": "".join(segment["text"] for segment in normalized_segments).strip(),
        "segments": normalized_segments,
        "language": str(getattr(info, "language", language or "unknown")),
        "language_probability": float(getattr(info, "language_probability", 0.0)),
    }


@lru_cache(maxsize=3)
def _faster_whisper_model(model_name: str, device: str, compute_type: str, download_root: str | None) -> Any:
    try:
        from faster_whisper import WhisperModel  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - Docker/runtime dependency.
        raise RuntimeError("faster-whisper is required for the Docker ASR provider") from exc
    return WhisperModel(model_name, device=device, compute_type=compute_type, download_root=download_root)


def _select_asr_provider(configured: str, installed: dict[str, bool]) -> str | None:
    aliases = {"mlx": "mlx-whisper", "faster": "faster-whisper"}
    configured = aliases.get(configured, configured)
    if configured == "auto":
        return next((provider for provider in ("mlx-whisper", "faster-whisper") if installed[provider]), None)
    if configured not in installed:
        return None
    return configured if installed[configured] else None


def _asr_unavailable_message(configured: str) -> str:
    if configured == "auto":
        return "mlx-whisper 또는 faster-whisper가 필요합니다."
    return f"설정된 ASR 제공자({configured})가 설치되어 있지 않습니다."


def _segment_to_input_segment(
    index: int,
    segment: dict[str, Any],
    asr_model: str,
    confidence_threshold: float,
) -> dict[str, Any]:
    avg_logprob = float(segment.get("avg_logprob", -10.0))
    flags = [f"asr_from_{_flag_safe(asr_model)}"]
    if math.isfinite(avg_logprob):
        confidence = round(math.exp(avg_logprob), 3)
    else:
        confidence = 0.0
        flags.append("asr_confidence_unavailable")
    if confidence < confidence_threshold:
        flags.append("low_confidence_asr")

    no_speech_prob = segment.get("no_speech_prob")
    text = " ".join(str(segment.get("text", "")).split())
    return {
        "segment_id": f"asr-{index:03d}",
        "start_ms": int(round(float(segment.get("start", 0.0)) * 1000)),
        "end_ms": int(round(float(segment.get("end", 0.0)) * 1000)),
        "speaker_candidates": ["SPK1"],
        "text": text,
        "asr_text": text,
        "confidence": confidence,
        "flags": flags,
        "evidence_notes": f"{asr_model} avg_logprob={avg_logprob:.3f}, no_speech_prob={no_speech_prob}",
    }


def _is_usable_asr_segment(segment: Any) -> bool:
    if not isinstance(segment, dict) or not " ".join(str(segment.get("text", "")).split()):
        return False
    try:
        start = float(segment.get("start", 0.0))
        end = float(segment.get("end", 0.0))
    except (TypeError, ValueError):
        return False
    return math.isfinite(start) and math.isfinite(end) and start >= 0 and end > start


def _source_media(
    media_path: Path,
    media_probe: dict[str, Any],
    asr_model: str,
    asr_engine: str,
) -> dict[str, Any]:
    video = _first_stream(media_probe, "video")
    audio = _first_stream(media_probe, "audio")
    return {
        "path": str(media_path),
        "container": media_path.suffix.lstrip(".").lower() or "unknown",
        "duration_seconds": _duration_seconds(media_probe),
        "size_bytes": _size_bytes(media_probe),
        "selection_reason": "User-provided media input for automated subtitle preparation",
        "asr_engine": asr_engine,
        "asr_model": asr_model,
        "video": video,
        "audio": audio,
    }


def _duration_seconds(media_probe: dict[str, Any]) -> float:
    duration = (media_probe.get("format") or {}).get("duration")
    if duration is None:
        return 0.0
    return round(float(duration), 3)


def _size_bytes(media_probe: dict[str, Any]) -> int:
    size = (media_probe.get("format") or {}).get("size")
    return int(size) if size is not None else 0


def _first_stream(media_probe: dict[str, Any], codec_type: str) -> dict[str, Any] | None:
    for stream in media_probe.get("streams", []):
        if stream.get("codec_type") == codec_type:
            return dict(stream)
    return None


def _flag_safe(value: str) -> str:
    return "".join(char if char.isalnum() else "_" for char in value.lower()).strip("_")


def _default_audio_path(media_path: Path, work_dir: Path | None) -> Path:
    root = Path(work_dir) if work_dir else media_path.parent
    return root / f"{media_path.stem}_16k_mono.wav"


def _whisper_language(value: str) -> str | None:
    normalized = value.strip().lower().replace("_", "-")
    if not normalized or normalized in {"auto", "unknown"}:
        return None
    return normalized.split("-", 1)[0]


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
