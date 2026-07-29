"""LLM-backed stage execution with conservative fallback behavior."""

from __future__ import annotations

from typing import Any

from .local_llm import LocalLLMClient, extract_json_payload, extract_message_content
from .pipeline import segment_input_locally
from .prompts import build_prompt_job


def run_stage_with_local_llm(
    stage: str,
    job: dict[str, Any],
    *,
    client: LocalLLMClient | Any | None = None,
    fallback: str = "none",
    max_tokens: int = 4096,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run a stage through the local LLM and return (stage_result, raw_response)."""

    llm_client = client or LocalLLMClient()
    prompt_bundle = build_prompt_job(stage, job)
    raw_response = llm_client.chat(
        [
            {"role": "system", "content": prompt_bundle["system_prompt"]},
            {"role": "user", "content": _with_json_guard(prompt_bundle["user_prompt"])},
        ],
        max_tokens=max_tokens,
    )
    content = extract_message_content(raw_response)
    try:
        result = extract_json_payload(content)
        _normalize_result_contract(result, job)
        _attach_metadata(result, llm_client, raw_response, parsed=True, fallback="none")
        return result, raw_response
    except ValueError as exc:
        if fallback == "local" and stage.upper() == "SEGMENT-SUB":
            result = segment_input_locally(job)
            result.setdefault("warnings", []).append("local_llm_invalid_json_fallback_used")
            _attach_metadata(
                result,
                llm_client,
                raw_response,
                parsed=False,
                fallback="local",
                parse_error=str(exc),
            )
            return result, raw_response
        return _recoverable_error(stage, job, llm_client, raw_response, str(exc)), raw_response


def _attach_metadata(
    result: dict[str, Any],
    client: Any,
    raw_response: dict[str, Any],
    *,
    parsed: bool,
    fallback: str,
    parse_error: str | None = None,
) -> None:
    result["llm_metadata"] = {
        "provider": "local_openai_compatible",
        "base_url": getattr(client, "base_url", "unknown"),
        "model": raw_response.get("model", getattr(client, "model", "unknown")),
        "used": True,
        "parsed": parsed,
        "fallback": fallback,
        "finish_reason": _finish_reason(raw_response),
    }
    if parse_error:
        result["llm_metadata"]["parse_error"] = parse_error


def _recoverable_error(
    stage: str,
    job: dict[str, Any],
    client: Any,
    raw_response: dict[str, Any],
    message: str,
) -> dict[str, Any]:
    result = {
        "job_id": job.get("job_id", "subtitle-job"),
        "stage": stage,
        "error": {
            "type": "recoverable_error",
            "code": "local_llm_invalid_json",
            "message": message,
            "missing_fields": [],
        },
    }
    _attach_metadata(result, client, raw_response, parsed=False, fallback="none", parse_error=message)
    return result


def _finish_reason(raw_response: dict[str, Any]) -> str | None:
    try:
        return raw_response["choices"][0].get("finish_reason")
    except (KeyError, IndexError, TypeError):
        return None


def _with_json_guard(user_prompt: str) -> str:
    return (
        f"{user_prompt}\n\n"
        "<final_output_guard>\n"
        "Return the final JSON object immediately. The first non-whitespace character must be {.\n"
        "Do not include analysis, reasoning, markdown, labels, or commentary before or after the JSON object.\n"
        "</final_output_guard>"
    )


def _normalize_result_contract(result: dict[str, Any], job: dict[str, Any]) -> None:
    expected_job_id = job.get("job_id")
    if expected_job_id and result.get("job_id") != expected_job_id:
        result["job_id"] = expected_job_id
        result.setdefault("warnings", []).append("local_llm_job_id_normalized")
    _repair_subtitle_cues(result, job.get("policies", {}))


def _repair_subtitle_cues(result: dict[str, Any], policies: dict[str, Any]) -> None:
    cues = result.get("subtitle_cues")
    if not isinstance(cues, list):
        return
    max_lines = int(policies.get("max_lines_per_cue", 2))
    if max_lines <= 0:
        return

    repaired: list[dict[str, Any]] = []
    changed = False
    for cue in cues:
        lines = cue.get("lines", [])
        if not isinstance(lines, list) or len(lines) <= max_lines:
            repaired.append(cue)
            continue

        changed = True
        groups = [lines[index : index + max_lines] for index in range(0, len(lines), max_lines)]
        start_ms = int(cue.get("start_ms", 0))
        end_ms = int(cue.get("end_ms", start_ms))
        for index, group in enumerate(groups):
            new_cue = dict(cue)
            new_cue["cue_id"] = f"{cue.get('cue_id', 'cue')}_{index + 1}"
            new_cue["start_ms"], new_cue["end_ms"] = _slice_time(start_ms, end_ms, index, len(groups))
            new_cue["lines"] = list(group)
            new_cue["chars_per_line"] = [len(str(line)) for line in group]
            new_cue["cps"] = _cps(group, new_cue["start_ms"], new_cue["end_ms"])
            repaired.append(new_cue)

    if changed:
        result["subtitle_cues"] = repaired
        result.setdefault("warnings", []).append("local_llm_cue_policy_repaired")


def _slice_time(start_ms: int, end_ms: int, index: int, count: int) -> tuple[int, int]:
    if end_ms <= start_ms or count <= 1:
        return start_ms, end_ms
    duration = end_ms - start_ms
    cue_start = start_ms + round(duration * index / count)
    cue_end = start_ms + round(duration * (index + 1) / count)
    return cue_start, cue_end


def _cps(lines: list[str], start_ms: int, end_ms: int) -> float:
    duration_seconds = max((end_ms - start_ms) / 1000, 0.001)
    chars = sum(len(str(line).replace(" ", "")) for line in lines)
    return round(chars / duration_seconds, 2)
