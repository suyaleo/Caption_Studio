"""End-to-end runner for complete subtitle deliverable sets."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .formats import cues_to_srt, cues_to_vtt
from .llm_pipeline import run_stage_with_local_llm
from .local_llm import LocalLLMClient
from .pipeline import segment_input_locally
from .prompts import build_prompt_job
from .validation import validate_subtitle_job


def run_complete_job(
    job: dict[str, Any],
    output_dir: Path,
    *,
    mode: str = "llm",
    stage: str = "SEGMENT-SUB",
    client: LocalLLMClient | Any | None = None,
    fallback: str = "local",
    max_tokens: int = 4096,
) -> dict[str, Any]:
    """Run prompt rendering, stage execution, QA, formatting, and manifest writing."""

    paths = _paths(output_dir)
    for directory in {path.parent for path in paths.values()}:
        directory.mkdir(parents=True, exist_ok=True)

    prompt_bundle = build_prompt_job(stage, job)
    _write_json(paths["prompt"], prompt_bundle)

    raw_response = None
    if mode == "llm":
        result, raw_response = run_stage_with_local_llm(
            stage,
            job,
            client=client or LocalLLMClient(),
            fallback=fallback,
            max_tokens=max_tokens,
        )
        _write_json(paths["raw"], raw_response)
    elif mode == "local":
        result = segment_input_locally(job)
    else:
        raise ValueError("mode must be 'llm' or 'local'")

    _write_json(paths["cues"], result)
    qa_report = validate_subtitle_job(result, job.get("policies", {}))
    if mode == "llm" and fallback == "local" and not qa_report.get("passed"):
        result = _fallback_after_qa(job, result, raw_response)
        _write_json(paths["cues"], result)
        qa_report = validate_subtitle_job(result, job.get("policies", {}))
    _write_json(paths["qa"], qa_report)
    cues = result.get("subtitle_cues", [])
    paths["srt"].write_text(cues_to_srt(cues), encoding="utf-8")
    paths["vtt"].write_text(cues_to_vtt(cues), encoding="utf-8")

    manifest = _manifest(job, result, qa_report, mode, stage, paths, output_dir, raw_response)
    _write_json(paths["manifest"], manifest)
    paths["acceptance"].write_text(_acceptance_report(manifest, result, qa_report), encoding="utf-8")
    if not qa_report.get("passed"):
        raise RuntimeError(f"QA failed; see {paths['qa']}")
    return manifest


def _paths(output_dir: Path) -> dict[str, Path]:
    return {
        "prompt": output_dir / "prompts" / "segment_sub_prompt.json",
        "raw": output_dir / "reports" / "local_llm_raw.json",
        "cues": output_dir / "subtitles" / "cues.json",
        "qa": output_dir / "reports" / "qa.json",
        "srt": output_dir / "subtitles" / "output.srt",
        "vtt": output_dir / "subtitles" / "output.vtt",
        "manifest": output_dir / "reports" / "manifest.json",
        "acceptance": output_dir / "reports" / "acceptance.md",
    }


def _manifest(
    job: dict[str, Any],
    result: dict[str, Any],
    qa_report: dict[str, Any],
    mode: str,
    stage: str,
    paths: dict[str, Path],
    output_dir: Path,
    raw_response: dict[str, Any] | None,
) -> dict[str, Any]:
    llm_metadata = result.get("llm_metadata", {"used": False})
    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "job_id": result.get("job_id", job.get("job_id", "subtitle-job")),
        "stage": stage,
        "mode": mode,
        "status": "passed" if qa_report.get("passed") else "failed",
        "qa_passed": bool(qa_report.get("passed")),
        "cue_count": len(result.get("subtitle_cues", [])),
        "warning_count": len(result.get("warnings", [])) + len(qa_report.get("warnings", [])),
        "flag_count": len(qa_report.get("flags", [])),
        "llm": {
            "used": bool(llm_metadata.get("used", False)),
            "model": llm_metadata.get("model"),
            "parsed": llm_metadata.get("parsed"),
            "fallback": llm_metadata.get("fallback"),
            "finish_reason": llm_metadata.get("finish_reason"),
            "raw_response_id": raw_response.get("id") if raw_response else None,
        },
        "artifacts": {name: _relative(path, output_dir) for name, path in paths.items()},
    }


def _fallback_after_qa(
    job: dict[str, Any],
    previous_result: dict[str, Any],
    raw_response: dict[str, Any] | None,
) -> dict[str, Any]:
    result = segment_input_locally(job)
    result.setdefault("warnings", []).append("local_llm_qa_failed_fallback_used")
    previous_metadata = previous_result.get("llm_metadata", {})
    result["llm_metadata"] = {
        "provider": "local_openai_compatible",
        "base_url": previous_metadata.get("base_url"),
        "model": previous_metadata.get("model") or (raw_response or {}).get("model"),
        "used": True,
        "parsed": previous_metadata.get("parsed"),
        "fallback": "local_after_qa",
        "finish_reason": previous_metadata.get("finish_reason") or _finish_reason(raw_response),
    }
    return result


def _finish_reason(raw_response: dict[str, Any] | None) -> str | None:
    if not raw_response:
        return None
    try:
        return raw_response["choices"][0].get("finish_reason")
    except (KeyError, IndexError, TypeError):
        return None


def _acceptance_report(manifest: dict[str, Any], result: dict[str, Any], qa_report: dict[str, Any]) -> str:
    warnings = result.get("warnings", []) + qa_report.get("warnings", [])
    lines = [
        "# Subtitle Automation Acceptance Report",
        "",
        f"- job_id: {manifest['job_id']}",
        f"- mode: {manifest['mode']}",
        f"- status: {manifest['status']}",
        f"- qa_passed: {manifest['qa_passed']}",
        f"- cue_count: {manifest['cue_count']}",
        f"- llm_model: {manifest['llm'].get('model')}",
        f"- llm_parsed: {manifest['llm'].get('parsed')}",
        f"- llm_fallback: {manifest['llm'].get('fallback')}",
        "",
        "## QA Flags",
        "",
    ]
    if qa_report.get("flags"):
        lines.extend(f"- {flag.get('cue_id')}: {flag.get('code')} - {flag.get('message')}" for flag in qa_report["flags"])
    else:
        lines.append("- none")
    lines.extend(["", "## Warnings", ""])
    if warnings:
        lines.extend(f"- {_format_warning(warning)}" for warning in warnings)
    else:
        lines.append("- none")
    lines.extend(["", "## Artifacts", ""])
    lines.extend(f"- {name}: {path}" for name, path in manifest["artifacts"].items())
    return "\n".join(lines) + "\n"


def _relative(path: Path, output_dir: Path) -> str:
    try:
        return str(path.relative_to(output_dir.parent))
    except ValueError:
        return str(path)


def _format_warning(warning: Any) -> str:
    if isinstance(warning, str):
        return warning
    return json.dumps(warning, ensure_ascii=False, sort_keys=True)


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
