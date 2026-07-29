"""Local validation and QA checks for subtitle cue results."""

from __future__ import annotations

from typing import Any


def validate_subtitle_job(result: dict[str, Any], policies: dict[str, Any] | None = None) -> dict[str, Any]:
    policies = policies or {}
    max_chars = int(policies.get("max_chars_per_line", 16))
    max_lines = int(policies.get("max_lines_per_cue", 2))
    max_cps = float(policies.get("max_cps", 15))
    allow_overlap = bool(policies.get("allow_overlap", False))
    flags: list[dict[str, Any]] = []
    warnings: list[str] = []
    previous_end: int | None = None
    subtitle_cues = result.get("subtitle_cues", [])

    if not subtitle_cues:
        flags.append(_flag("job", "missing_subtitle_cues", "Result must contain at least one subtitle cue."))

    for index, cue in enumerate(subtitle_cues, 1):
        cue_id = cue.get("cue_id", f"cue-{index}")
        start_ms = cue.get("start_ms")
        end_ms = cue.get("end_ms")
        lines = cue.get("lines", [])

        if not isinstance(start_ms, int) or not isinstance(end_ms, int) or start_ms < 0 or end_ms <= start_ms:
            flags.append(_flag(cue_id, "timestamp_invalid", "Cue timestamp must be non-negative and end after start."))

        if previous_end is not None and isinstance(start_ms, int) and start_ms < previous_end and not allow_overlap:
            flags.append(_flag(cue_id, "timestamp_not_monotonic", "Cue starts before the previous cue ends."))

        if isinstance(end_ms, int):
            previous_end = max(previous_end or 0, end_ms)

        if not isinstance(lines, list) or not lines:
            flags.append(_flag(cue_id, "missing_lines", "Cue must contain at least one subtitle line."))
            lines = []

        if len(lines) > max_lines:
            flags.append(_flag(cue_id, "max_lines_per_cue", f"Cue has more than {max_lines} lines."))

        for line_number, line in enumerate(lines, 1):
            if len(str(line)) > max_chars:
                flags.append(
                    _flag(
                        cue_id,
                        "max_chars_per_line",
                        f"Line {line_number} exceeds {max_chars} characters.",
                        observed=len(str(line)),
                    )
                )

        cps = cue.get("cps")
        measured_cps = _measure_cps(cue)
        if cps is None:
            cue["cps"] = measured_cps
            cps = measured_cps
        if float(cps) > max_cps:
            flags.append(_flag(cue_id, "max_cps", f"Cue exceeds max CPS {max_cps}.", observed=round(float(cps), 2)))

        if float(cue.get("confidence", 1.0)) < 0.6:
            flags.append(_flag(cue_id, "low_confidence", "Cue confidence is below review threshold."))

        if "unclear" in " ".join(str(line).lower() for line in lines):
            warnings.append(f"{cue_id}: unclear span should be reviewed.")

    return {
        "job_id": result.get("job_id", "unknown"),
        "stage": "qa_report",
        "passed": not flags,
        "flags": flags,
        "warnings": warnings,
    }


def _measure_cps(cue: dict[str, Any]) -> float:
    start_ms = cue.get("start_ms")
    end_ms = cue.get("end_ms")
    if not isinstance(start_ms, int) or not isinstance(end_ms, int) or end_ms <= start_ms:
        return 999.0
    chars = sum(len(str(line).replace(" ", "")) for line in cue.get("lines", []))
    duration_seconds = (end_ms - start_ms) / 1000
    return round(chars / duration_seconds, 2) if duration_seconds else 999.0


def _flag(cue_id: str, code: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"cue_id": cue_id, "code": code, "message": message, **extra}
