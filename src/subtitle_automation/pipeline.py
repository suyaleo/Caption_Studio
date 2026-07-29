"""Local deterministic subtitle helpers.

These helpers are intentionally conservative. They do not translate, infer
missing speech, or assign named speakers. Their job is to make the prompt kit
usable before an external LLM adapter is connected.
"""

from __future__ import annotations

from typing import Any


def segment_input_locally(job: dict[str, Any]) -> dict[str, Any]:
    policies = job.get("policies", {})
    max_chars = int(policies.get("max_chars_per_line", 16))
    max_lines = int(policies.get("max_lines_per_cue", 2))
    cues: list[dict[str, Any]] = []
    warnings: list[str] = []

    for segment in job.get("input_segments", []):
        text = _evidence_text(segment)
        speaker = _speaker(segment)
        base_flags = list(segment.get("flags", []))
        confidence = float(segment.get("confidence", 0.0))
        if confidence < 0.6 and "low_confidence" not in base_flags:
            base_flags.append("low_confidence")
        if text == "[unclear]" and "unclear_phrase" not in base_flags:
            base_flags.append("unclear_phrase")

        line_groups = _group_lines(_wrap_text(text, max_chars), max_lines)
        if len(line_groups) > 1:
            warnings.append(f"{segment.get('segment_id', 'unknown')}: split into {len(line_groups)} cues by policy.")

        for group_index, lines in enumerate(line_groups):
            start_ms, end_ms = _slice_time(
                int(segment.get("start_ms", 0)),
                int(segment.get("end_ms", segment.get("start_ms", 0))),
                group_index,
                len(line_groups),
            )
            cues.append(
                {
                    "cue_id": f"c{len(cues) + 1}",
                    "source_segment_id": segment.get("segment_id", ""),
                    "start_ms": start_ms,
                    "end_ms": end_ms,
                    "speaker": speaker,
                    "lines": lines,
                    "chars_per_line": [len(line) for line in lines],
                    "cps": _cps(lines, start_ms, end_ms),
                    "confidence": confidence,
                    "flags": list(base_flags),
                }
            )

    return {
        "job_id": job.get("job_id", "subtitle-job"),
        "stage": "subtitle_segmentation",
        "source_language": job.get("source_language_hint", "unknown"),
        "target_language": job.get("target_language", job.get("source_language_hint", "same_as_source")),
        "subtitle_cues": cues,
        "errors": [],
        "warnings": warnings,
    }


def _evidence_text(segment: dict[str, Any]) -> str:
    for key in ("text", "asr_text", "transcript"):
        value = str(segment.get(key, "")).strip()
        if value:
            return value
    return "[unclear]"


def _speaker(segment: dict[str, Any]) -> str:
    if segment.get("speaker"):
        return str(segment["speaker"])
    candidates = segment.get("speaker_candidates") or []
    return str(candidates[0]) if candidates else "SPK?"


def _wrap_text(text: str, max_chars: int) -> list[str]:
    if max_chars <= 0:
        raise ValueError("max_chars_per_line must be positive")
    words = text.split()
    if not words:
        return [text[:max_chars] or "[unclear]"]

    lines: list[str] = []
    current = ""
    for word in words:
        pieces = _split_long_word(word, max_chars)
        for piece in pieces:
            candidate = piece if not current else f"{current} {piece}"
            if len(candidate) <= max_chars:
                current = candidate
            else:
                if current:
                    lines.append(current)
                current = piece
    if current:
        lines.append(current)
    return lines or ["[unclear]"]


def _split_long_word(word: str, max_chars: int) -> list[str]:
    if len(word) <= max_chars:
        return [word]
    return [word[index : index + max_chars] for index in range(0, len(word), max_chars)]


def _group_lines(lines: list[str], max_lines: int) -> list[list[str]]:
    if max_lines <= 0:
        raise ValueError("max_lines_per_cue must be positive")
    return [lines[index : index + max_lines] for index in range(0, len(lines), max_lines)]


def _slice_time(start_ms: int, end_ms: int, index: int, count: int) -> tuple[int, int]:
    if end_ms <= start_ms or count <= 1:
        return start_ms, end_ms
    duration = end_ms - start_ms
    cue_start = start_ms + round(duration * index / count)
    cue_end = start_ms + round(duration * (index + 1) / count)
    return cue_start, cue_end


def _cps(lines: list[str], start_ms: int, end_ms: int) -> float:
    duration_seconds = max((end_ms - start_ms) / 1000, 0.001)
    chars = sum(len(line.replace(" ", "")) for line in lines)
    return round(chars / duration_seconds, 2)
