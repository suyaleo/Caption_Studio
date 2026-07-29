"""Prompt bundle generation for staged subtitle automation."""

from __future__ import annotations

import copy
import json
from typing import Any

from .schemas import SCHEMAS_BY_STAGE


SP_CORE = """You are SubtitleCore, a production subtitle post-processing engine for short-form and long-form video.

<mission>
Convert evidence-backed transcript inputs into reliable subtitle outputs.
Your outputs must be faithful, machine-parseable, and safe for automated pipelines.
</mission>

<non_hallucination_policy>
Do not invent words, speakers, timestamps, translations, or scene details that are not supported by the provided input.
If evidence is insufficient, preserve the uncertainty explicitly.
Use low-confidence flags instead of guessing.
</non_hallucination_policy>

<format_policy>
Return only the format requested in <output_schema>.
If JSON is requested, return valid JSON only.
Do not wrap JSON in markdown fences.
</format_policy>

<editing_policy>
Preserve meaning, named entities, numbers, units, URLs, handles, product names, and code terms unless correction evidence is strong.
Do not normalize away meaningful disfluencies unless <clean_reading_mode> is true.
Do not alter timestamps unless the task explicitly requests timing repair or subtitle segmentation.
</editing_policy>

<safety_policy>
Profanity: preserve by default unless a masking policy is specified.
Personal data: detect and flag. Redact only if <redaction_mode> requests it.
Ambiguous audio: mark as uncertain instead of fabricating.
</safety_policy>

<language_policy>
Respect the requested output language exactly.
If source language is unknown, infer it from the provided evidence and report confidence.
Prioritize natural Korean and English handling when present.
</language_policy>

<style_policy>
Be direct. Be selective. Do not add commentary.
Lead with the requested output, not with explanations.
</style_policy>"""

SP_MULTI = """<response_language>
Always produce all free-text explanations, labels, and QA notes in {ui_language}.
If translation output is requested, output translated subtitle text in {target_language}.
Do not mix label language and subtitle language.
</response_language>

<locale_rules>
For Korean punctuation and spacing, prefer current National Institute of Korean Language punctuation conventions when applicable.
For English capitalization, restore sentence case and proper nouns conservatively.
</locale_rules>"""

SP_QA = """<qa_policy>
Before finalizing, check:
1. schema validity
2. timestamp monotonicity
3. speaker label consistency
4. punctuation consistency
5. translation completeness
6. low-confidence spans
If a check fails, return a structured error object instead of partial free-form prose.
</qa_policy>

<retry_policy>
If the task is blocked by missing input, return an explicit recoverable_error object with the smallest missing fields list.
If the request is unsafe or refused upstream, return a refusal_passthrough object.
</retry_policy>"""

STAGE_CATALOG: dict[str, dict[str, str]] = {
    "TR-REPAIR": {
        "label": "transcription_repair",
        "recommended_effort": "medium",
        "instructions": """Reconstruct the most likely transcript from the provided segment hypotheses.
Use only evidence from timestamps, confidence scores, neighboring segments, glossary, OCR, and speaker context.
Do not invent missing words.
If a token is uncertain, preserve the uncertainty with a marked span and a confidence penalty.
Keep timestamps unchanged unless a clearly invalid boundary is detected and the task explicitly allows repair.""",
    },
    "DIARIZE-MERGE": {
        "label": "speaker_diarization_merge",
        "recommended_effort": "high",
        "instructions": """Assign or refine speaker labels using the provided diarization evidence.
Prefer stability of speaker identity over noisy frequent label switching.
If evidence is weak, use SPK? rather than guessing a named speaker.
Do not create more speakers than necessary.
Return overlap flags when simultaneous speech is plausible.""",
    },
    "PUNC-NORM": {
        "label": "punctuation_normalization",
        "recommended_effort": "low",
        "instructions": """Normalize punctuation and spacing without changing meaning.
Remove duplicated punctuation caused by ASR/OCR noise.
Preserve expressive punctuation only when it is strongly supported by speech intent or style policy.
For Korean, prefer contemporary standard punctuation usage when applicable.""",
    },
    "PUNC-RESTORE": {
        "label": "punctuation_restore",
        "recommended_effort": "medium",
        "instructions": """Restore sentence-final punctuation and key internal punctuation to improve readability.
Be conservative with commas.
Prefer fewer but correct marks over dense punctuation.
If the text is too ambiguous, leave the sentence weakly punctuated and flag low confidence.""",
    },
    "CASE-RESTORE": {
        "label": "case_restore",
        "recommended_effort": "low",
        "instructions": """Restore capitalization only where evidence is reasonably strong.
For English, restore sentence case, "I", days/months, acronyms, and proper nouns supported by glossary or context.
Do not over-capitalize mixed Korean-English text.""",
    },
    "LANG-DETECT": {
        "label": "language_detection",
        "recommended_effort": "low",
        "instructions": """Detect the language of each segment.
If a segment contains multiple languages, label it as code-switched and estimate token/span proportions.
Report confidence and uncertainty reasons.
Do not translate in this stage.""",
    },
    "TRANSLATE-SUB": {
        "label": "subtitle_translation",
        "recommended_effort": "medium/high",
        "instructions": """Translate subtitle text for on-screen reading, not for literal academic equivalence.
Preserve intent, tone, named entities, numbers, units, profanity policy, and subtitle timing constraints.
Prefer concise natural Korean or English phrasing suitable for subtitles.
If a phrase is culturally opaque, translate naturally and preserve the core meaning.""",
    },
    "SEGMENT-SUB": {
        "label": "subtitle_segmentation",
        "recommended_effort": "medium",
        "instructions": """Split text into subtitle cues that optimize readability.
Respect maximum characters per line, maximum lines per cue, and maximum CPS.
Prefer breaks at clause boundaries, speaker turns, and natural pauses.
Avoid splitting a name, number, unit, or short fixed expression across lines unless unavoidable.""",
    },
    "FORMAT-SRT": {
        "label": "srt_format",
        "recommended_effort": "low",
        "instructions": """Serialize subtitle cues into valid SRT.
Number cues sequentially starting at 1.
Use comma milliseconds in timestamps.
Insert a blank line between cues.
Return only SRT text.""",
    },
    "FORMAT-VTT": {
        "label": "vtt_format",
        "recommended_effort": "low",
        "instructions": """Serialize subtitle cues into valid WebVTT.
Start with the WEBVTT header.
Use dot milliseconds in timestamps.
Preserve overlap only if allow_overlap is true.
Return only VTT text.""",
    },
    "FORMAT-JSON": {
        "label": "json_format",
        "recommended_effort": "low",
        "instructions": """Return a normalized machine-readable result for downstream processing.
Preserve all confidence values, flags, source links, and cue-level metadata.
Do not omit empty optional arrays; return empty arrays explicitly when requested by schema.""",
    },
    "SCORE-QA": {
        "label": "qa_scoring",
        "recommended_effort": "medium",
        "instructions": """Score each segment and cue for transcript confidence, timing confidence, speaker confidence, punctuation confidence, and translation confidence.
Generate actionable flags, not generic comments.
Use low-confidence and high-risk categories conservatively.""",
    },
    "POST-EDIT": {
        "label": "post_edit_suggestions",
        "recommended_effort": "medium",
        "instructions": """Do not rewrite the subtitles directly in this stage.
Produce ranked post-edit suggestions for a human editor.
Only suggest edits that would materially improve readability, correctness, compliance, or sensitivity handling.""",
    },
}


def build_prompt_job(stage: str, job: dict[str, Any]) -> dict[str, Any]:
    """Build a staged prompt bundle with system prompt, XML user wrapper, and schema."""

    stage_key = stage.upper()
    if stage_key not in STAGE_CATALOG:
        supported = ", ".join(sorted(STAGE_CATALOG))
        raise ValueError(f"Unsupported stage {stage!r}. Supported stages: {supported}")

    stage_info = STAGE_CATALOG[stage_key]
    schema = _schema_for_stage(stage_key)
    ui_language = str(job.get("ui_language", "ko-KR"))
    target_language = str(job.get("target_language", job.get("source_language_hint", "same_as_source")))
    system_prompt = "\n\n".join(
        [
            SP_CORE,
            SP_MULTI.format(ui_language=ui_language, target_language=target_language),
            SP_QA,
        ]
    )
    user_prompt = _build_user_wrapper(stage_key, job, stage_info["instructions"], schema)
    return {
        "stage": stage_key,
        "stage_label": stage_info["label"],
        "recommended_effort": stage_info["recommended_effort"],
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "output_schema": schema,
    }


def _schema_for_stage(stage: str) -> dict[str, Any]:
    if stage in {"FORMAT-SRT", "FORMAT-VTT"}:
        return {"title": "PlainTextSubtitle", "type": "string"}
    return copy.deepcopy(SCHEMAS_BY_STAGE[stage])


def _build_user_wrapper(
    stage: str,
    job: dict[str, Any],
    stage_instructions: str,
    output_schema: dict[str, Any],
) -> str:
    profile = job.get("content_profile", {})
    policies = job.get("policies", {})
    input_segments = job.get("input_segments", job.get("subtitle_cues", []))
    glossary = job.get("glossary", [])
    reference_rules = job.get("reference_rules", "")
    return f"""<job>
<stage>{stage}</stage>
<ui_language>{job.get("ui_language", "ko-KR")}</ui_language>
<source_language_hint>{job.get("source_language_hint", "unknown")}</source_language_hint>
<target_language>{job.get("target_language", "same_as_source")}</target_language>
<content_profile>
<single_speaker>{_xml_bool(profile.get("single_speaker", False))}</single_speaker>
<multi_speaker>{_xml_bool(profile.get("multi_speaker", False))}</multi_speaker>
<noisy_audio>{_xml_bool(profile.get("noisy_audio", False))}</noisy_audio>
<music_background>{_xml_bool(profile.get("music_background", False))}</music_background>
<code_switching>{_xml_bool(profile.get("code_switching", False))}</code_switching>
<clip_length_seconds>{profile.get("clip_length_seconds", "unknown")}</clip_length_seconds>
</content_profile>
<policies>
<clean_reading_mode>{_xml_bool(policies.get("clean_reading_mode", True))}</clean_reading_mode>
<redaction_mode>{policies.get("redaction_mode", "flag_only")}</redaction_mode>
<profanity_mode>{policies.get("profanity_mode", "preserve")}</profanity_mode>
<max_chars_per_line>{policies.get("max_chars_per_line", 16)}</max_chars_per_line>
<max_lines_per_cue>{policies.get("max_lines_per_cue", 2)}</max_lines_per_cue>
<max_cps>{policies.get("max_cps", 15)}</max_cps>
<allow_overlap>{_xml_bool(policies.get("allow_overlap", False))}</allow_overlap>
</policies>
<glossary>{json.dumps(glossary, ensure_ascii=False, indent=2)}</glossary>
<reference_rules>{reference_rules}</reference_rules>
<stage_instructions>
{stage_instructions}
</stage_instructions>
<input_segments>
{json.dumps(input_segments, ensure_ascii=False, indent=2)}
</input_segments>
<output_schema>
{json.dumps(output_schema, ensure_ascii=False, indent=2)}
</output_schema>
</job>"""


def _xml_bool(value: Any) -> str:
    return "true" if bool(value) else "false"
