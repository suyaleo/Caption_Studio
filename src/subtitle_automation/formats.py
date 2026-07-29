"""Subtitle serialization helpers."""

from __future__ import annotations

from typing import Iterable


def cues_to_srt(cues: Iterable[dict]) -> str:
    blocks = []
    for index, cue in enumerate(cues, 1):
        lines = _lines(cue)
        blocks.append(
            "\n".join(
                [
                    str(index),
                    f"{format_timestamp(cue['start_ms'], separator=',')} --> {format_timestamp(cue['end_ms'], separator=',')}",
                    *lines,
                ]
            )
        )
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def cues_to_vtt(cues: Iterable[dict]) -> str:
    blocks = ["WEBVTT"]
    for cue in cues:
        lines = _lines(cue)
        blocks.append(
            "\n".join(
                [
                    f"{format_timestamp(cue['start_ms'], separator='.') } --> {format_timestamp(cue['end_ms'], separator='.')}",
                    *lines,
                ]
            )
        )
    return "\n\n".join(blocks) + "\n"


def format_timestamp(milliseconds: int, separator: str) -> str:
    if milliseconds < 0:
        raise ValueError("timestamp cannot be negative")
    hours, remainder = divmod(int(milliseconds), 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1_000)
    return f"{hours:02}:{minutes:02}:{seconds:02}{separator}{millis:03}"


def _lines(cue: dict) -> list[str]:
    raw_lines = cue.get("lines", [])
    if not isinstance(raw_lines, list) or not raw_lines:
        text = str(cue.get("text", "")).strip()
        return [text] if text else []
    return [str(line) for line in raw_lines]
