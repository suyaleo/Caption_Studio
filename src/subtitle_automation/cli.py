"""Command line interface for subtitle prompt and format automation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .formats import cues_to_srt, cues_to_vtt
from .llm_pipeline import run_stage_with_local_llm
from .local_llm import LocalLLMClient
from .media_input import prepare_media_input_job
from .pipeline import segment_input_locally
from .prompts import STAGE_CATALOG, build_prompt_job
from .runner import run_complete_job
from .validation import validate_subtitle_job


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="subtitle-automation")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prompt_parser = subparsers.add_parser("render-prompt", help="Render a staged prompt bundle as JSON.")
    prompt_parser.add_argument("--stage", required=True, choices=sorted(STAGE_CATALOG))
    prompt_parser.add_argument("--input", required=True, type=Path)
    prompt_parser.add_argument("--output", type=Path)
    prompt_parser.set_defaults(handler=_render_prompt)

    segment_parser = subparsers.add_parser("segment-local", help="Create conservative local subtitle cues from ASR segments.")
    segment_parser.add_argument("--input", required=True, type=Path)
    segment_parser.add_argument("--output", type=Path)
    segment_parser.set_defaults(handler=_segment_local)

    llm_parser = subparsers.add_parser("llm-stage", help="Run a stage with the configured local OpenAI-compatible LLM.")
    llm_parser.add_argument("--stage", required=True, choices=sorted(STAGE_CATALOG))
    llm_parser.add_argument("--input", required=True, type=Path)
    llm_parser.add_argument("--output", type=Path)
    llm_parser.add_argument("--raw-output", type=Path, help="Write the raw chat completion response for evidence.")
    llm_parser.add_argument("--fallback", choices=["none", "local"], default="local")
    llm_parser.add_argument("--max-tokens", type=int, default=4096)
    llm_parser.set_defaults(handler=_llm_stage)

    run_parser = subparsers.add_parser("run-all", help="Run prompt, local LLM/local stage, QA, SRT/VTT, and manifest.")
    run_parser.add_argument("--input", required=True, type=Path)
    run_parser.add_argument("--output-dir", required=True, type=Path)
    run_parser.add_argument("--mode", choices=["llm", "local"], default="llm")
    run_parser.add_argument("--stage", choices=sorted(STAGE_CATALOG), default="SEGMENT-SUB")
    run_parser.add_argument("--fallback", choices=["none", "local"], default="local")
    run_parser.add_argument("--max-tokens", type=int, default=4096)
    run_parser.set_defaults(handler=_run_all)

    prepare_media_parser = subparsers.add_parser(
        "prepare-mp4-input",
        help="Build a run-all input job from an MP4 and ASR evidence.",
    )
    _add_media_preparation_args(prepare_media_parser)
    prepare_media_parser.add_argument("--output", required=True, type=Path)
    prepare_media_parser.set_defaults(handler=_prepare_mp4_input)

    run_media_parser = subparsers.add_parser(
        "run-media",
        help="Prepare MP4 input, run subtitle generation, and write an automated review report.",
    )
    _add_media_preparation_args(run_media_parser)
    run_media_parser.add_argument("--output-dir", required=True, type=Path)
    run_media_parser.add_argument("--mode", choices=["llm", "local"], default="local")
    run_media_parser.add_argument("--stage", choices=sorted(STAGE_CATALOG), default="SEGMENT-SUB")
    run_media_parser.add_argument("--fallback", choices=["none", "local"], default="local")
    run_media_parser.add_argument("--max-tokens", type=int, default=4096)
    run_media_parser.set_defaults(handler=_run_media)

    validate_parser = subparsers.add_parser("validate", help="Validate subtitle cue JSON against timing and UI policies.")
    validate_parser.add_argument("--input", required=True, type=Path)
    validate_parser.add_argument("--policies", type=Path)
    validate_parser.add_argument("--output", type=Path)
    validate_parser.set_defaults(handler=_validate)

    srt_parser = subparsers.add_parser("format-srt", help="Serialize subtitle cue JSON as SRT.")
    srt_parser.add_argument("--input", required=True, type=Path)
    srt_parser.add_argument("--output", type=Path)
    srt_parser.set_defaults(handler=_format_srt)

    vtt_parser = subparsers.add_parser("format-vtt", help="Serialize subtitle cue JSON as WebVTT.")
    vtt_parser.add_argument("--input", required=True, type=Path)
    vtt_parser.add_argument("--output", type=Path)
    vtt_parser.set_defaults(handler=_format_vtt)

    args = parser.parse_args(argv)
    try:
        args.handler(args)
    except Exception as exc:  # pragma: no cover - exercised manually by CLI users.
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def _render_prompt(args: argparse.Namespace) -> None:
    job = _read_json(args.input)
    _write_json_or_stdout(build_prompt_job(args.stage, job), args.output)


def _segment_local(args: argparse.Namespace) -> None:
    job = _read_json(args.input)
    _write_json_or_stdout(segment_input_locally(job), args.output)


def _llm_stage(args: argparse.Namespace) -> None:
    job = _read_json(args.input)
    result, raw_response = run_stage_with_local_llm(
        args.stage,
        job,
        client=LocalLLMClient(),
        fallback=args.fallback,
        max_tokens=args.max_tokens,
    )
    if args.raw_output:
        _write_json_or_stdout(raw_response, args.raw_output)
    _write_json_or_stdout(result, args.output)


def _run_all(args: argparse.Namespace) -> None:
    job = _read_json(args.input)
    manifest = run_complete_job(
        job,
        args.output_dir,
        mode=args.mode,
        stage=args.stage,
        client=LocalLLMClient() if args.mode == "llm" else None,
        fallback=args.fallback,
        max_tokens=args.max_tokens,
    )
    _write_json_or_stdout(manifest, None)


def _prepare_mp4_input(args: argparse.Namespace) -> None:
    job = _prepare_media_job_from_args(args)
    _write_json_or_stdout(job, args.output)


def _run_media(args: argparse.Namespace) -> None:
    output_dir = args.output_dir
    reports_dir = output_dir / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    if not args.media_probe_output:
        args.media_probe_output = reports_dir / "media_probe.json"
    if not args.raw_asr_output:
        args.raw_asr_output = reports_dir / "asr_raw.json"
    if not args.audio_output and not args.asr_json:
        args.audio_output = output_dir / "audio" / "source_16k_mono.wav"
    if not args.work_dir:
        args.work_dir = output_dir / "work"

    job = _prepare_media_job_from_args(args)
    input_job_path = output_dir / "input_job.json"
    _write_json_or_stdout(job, input_job_path)

    run_all_dir = output_dir / "run_all"
    manifest: dict[str, Any] | None = None
    run_error: Exception | None = None
    try:
        manifest = run_complete_job(
            job,
            run_all_dir,
            mode=args.mode,
            stage=args.stage,
            client=LocalLLMClient() if args.mode == "llm" else None,
            fallback=args.fallback,
            max_tokens=args.max_tokens,
        )
    except RuntimeError as exc:
        run_error = exc
        manifest = _read_json_if_exists(run_all_dir / "reports" / "manifest.json")

    qa_report = _read_json_if_exists(run_all_dir / "reports" / "qa.json")
    review_path = output_dir / "review_report.md"
    review_path.write_text(
        _build_media_review_report(
            job=job,
            output_dir=output_dir,
            input_job_path=input_job_path,
            run_all_dir=run_all_dir,
            manifest=manifest,
            qa_report=qa_report,
            run_error=run_error,
            args=args,
        ),
        encoding="utf-8",
    )

    if run_error:
        raise RuntimeError(f"media run failed; see {review_path}") from run_error
    _write_json_or_stdout(manifest or {}, None)


def _validate(args: argparse.Namespace) -> None:
    result = _read_json(args.input)
    policy_source = _read_json(args.policies) if args.policies else result
    policies = policy_source.get("policies", policy_source)
    _write_json_or_stdout(validate_subtitle_job(result, policies), args.output)


def _format_srt(args: argparse.Namespace) -> None:
    data = _read_json(args.input)
    _write_text_or_stdout(cues_to_srt(_extract_cues(data)), args.output)


def _format_vtt(args: argparse.Namespace) -> None:
    data = _read_json(args.input)
    _write_text_or_stdout(cues_to_vtt(_extract_cues(data)), args.output)


def _extract_cues(data: dict[str, Any]) -> list[dict[str, Any]]:
    if "subtitle_cues" in data:
        return list(data["subtitle_cues"])
    if "cues" in data:
        return list(data["cues"])
    raise ValueError("input JSON must contain subtitle_cues or cues")


def _add_media_preparation_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--media", required=True, type=Path)
    parser.add_argument("--job-id", default="media-subtitle-job")
    parser.add_argument("--asr-model", default="mlx-community/whisper-small-mlx")
    parser.add_argument("--source-language", default="ko-KR")
    parser.add_argument("--target-language", default="ko-KR")
    parser.add_argument("--asr-json", type=Path, help="Use an existing Whisper-style ASR JSON file.")
    parser.add_argument("--media-probe-json", type=Path, help="Use an existing ffprobe JSON file.")
    parser.add_argument("--raw-asr-output", type=Path, help="Write or copy the raw ASR evidence JSON.")
    parser.add_argument("--media-probe-output", type=Path, help="Write or copy the media probe evidence JSON.")
    parser.add_argument("--audio-output", type=Path, help="Write extracted 16 kHz mono WAV here when ASR is run.")
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--max-chars-per-line", type=int)
    parser.add_argument("--max-lines-per-cue", type=int)
    parser.add_argument("--max-cps", type=float)
    parser.add_argument("--allow-overlap", action="store_true", default=None)


def _prepare_media_job_from_args(args: argparse.Namespace) -> dict[str, Any]:
    return prepare_media_input_job(
        media_path=args.media,
        job_id=args.job_id,
        asr_model=args.asr_model,
        source_language=args.source_language,
        target_language=args.target_language,
        policies=_policy_overrides(args),
        work_dir=args.work_dir,
        asr_json_path=args.asr_json,
        media_probe_json_path=args.media_probe_json,
        raw_asr_output=args.raw_asr_output,
        media_probe_output=args.media_probe_output,
        audio_output=args.audio_output,
    )


def _policy_overrides(args: argparse.Namespace) -> dict[str, Any]:
    mapping = {
        "max_chars_per_line": args.max_chars_per_line,
        "max_lines_per_cue": args.max_lines_per_cue,
        "max_cps": args.max_cps,
        "allow_overlap": args.allow_overlap,
    }
    return {key: value for key, value in mapping.items() if value is not None}


def _build_media_review_report(
    *,
    job: dict[str, Any],
    output_dir: Path,
    input_job_path: Path,
    run_all_dir: Path,
    manifest: dict[str, Any] | None,
    qa_report: dict[str, Any] | None,
    run_error: Exception | None,
    args: argparse.Namespace,
) -> str:
    source_media = job.get("source_media", {})
    qa_passed = bool((qa_report or {}).get("passed"))
    status = (manifest or {}).get("status") or ("passed" if qa_passed else "failed")
    verdict = "release-ready" if qa_passed and not run_error else "not release-ready"
    flags = (qa_report or {}).get("flags") or []
    warnings = (qa_report or {}).get("warnings") or []
    lines = [
        "# Media Subtitle Automation Review",
        "",
        "## Source Media",
        "",
        f"- path: {source_media.get('path')}",
        f"- duration_seconds: {source_media.get('duration_seconds')}",
        f"- size_bytes: {source_media.get('size_bytes')}",
        f"- asr_engine: {source_media.get('asr_engine')}",
        f"- asr_model: {source_media.get('asr_model')}",
        "",
        "## Run Outputs",
        "",
        f"- input_job: {_relative_path(input_job_path, output_dir)}",
        f"- run_all_dir: {_relative_path(run_all_dir, output_dir)}",
        f"- media_probe: {_relative_path(args.media_probe_output, output_dir) if args.media_probe_output else 'not written'}",
        f"- raw_asr: {_relative_path(args.raw_asr_output, output_dir) if args.raw_asr_output else 'not written'}",
        f"- audio: {_relative_path(args.audio_output, output_dir) if args.audio_output else 'not extracted in this run'}",
        "",
        "## Review Verdict",
        "",
        f"- verdict: {verdict}",
        f"- status: {status}",
        f"- qa_passed: {qa_passed}",
        f"- mode: {args.mode}",
        f"- run_error: {run_error or 'none'}",
        "",
        "## QA Flags",
        "",
    ]
    if flags:
        lines.extend(f"- {flag.get('cue_id')}: {flag.get('code')} - {flag.get('message')}" for flag in flags)
    else:
        lines.append("- none")
    lines.extend(["", "## Warnings", ""])
    if warnings:
        lines.extend(f"- {warning}" for warning in warnings)
    else:
        lines.append("- none")
    lines.extend(["", "## Failure Record And Rework Plan", ""])
    if qa_passed and not run_error:
        lines.append("- no blocking failure recorded")
    else:
        lines.extend(
            [
                "- cause: automated generation or QA did not meet acceptance criteria",
                "- responsibility: current automation must preserve this failure instead of masking it",
                "- rework: confirm transcript manually or rerun with a stronger ASR/alignment source, then rerun run-media",
            ]
        )
    lines.extend(["", "## Verification Status", ""])
    lines.append("- review report generated after input preparation and run-all execution")
    lines.append("- user approval: pending")
    return "\n".join(lines) + "\n"


def _read_json_if_exists(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return _read_json(path)


def _relative_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _read_json(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json_or_stdout(data: dict[str, Any], path: Path | None) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    _write_text_or_stdout(text, path)


def _write_text_or_stdout(text: str, path: Path | None) -> None:
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    else:
        print(text, end="")


if __name__ == "__main__":
    raise SystemExit(main())
