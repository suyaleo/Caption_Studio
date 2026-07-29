"""Stable schema contracts derived from the PDF prompt design report."""

COMMON_SEGMENT_SCHEMA = {
    "title": "TranscriptSegments",
    "type": "object",
    "required": ["job_id", "stage", "source_language", "target_language", "segments", "errors", "warnings"],
    "properties": {
        "job_id": {"type": "string"},
        "stage": {"type": "string"},
        "source_language": {"type": "string"},
        "target_language": {"type": "string"},
        "segments": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "segment_id",
                    "start_ms",
                    "end_ms",
                    "speaker",
                    "text",
                    "confidence",
                    "flags",
                    "evidence_notes",
                ],
                "properties": {
                    "segment_id": {"type": "string"},
                    "start_ms": {"type": "integer", "minimum": 0},
                    "end_ms": {"type": "integer", "minimum": 0},
                    "speaker": {"type": "string"},
                    "text": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "flags": {"type": "array", "items": {"type": "string"}},
                    "evidence_notes": {"type": "string"},
                },
            },
        },
        "errors": {"type": "array"},
        "warnings": {"type": "array"},
    },
}

SUBTITLE_CUES_SCHEMA = {
    "title": "SubtitleCues",
    "type": "object",
    "required": ["job_id", "stage", "source_language", "target_language", "subtitle_cues", "errors", "warnings"],
    "properties": {
        "job_id": {"type": "string"},
        "stage": {"const": "subtitle_segmentation"},
        "source_language": {"type": "string"},
        "target_language": {"type": "string"},
        "subtitle_cues": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "cue_id",
                    "start_ms",
                    "end_ms",
                    "speaker",
                    "lines",
                    "chars_per_line",
                    "cps",
                    "confidence",
                    "flags",
                ],
                "properties": {
                    "cue_id": {"type": "string"},
                    "start_ms": {"type": "integer", "minimum": 0},
                    "end_ms": {"type": "integer", "minimum": 0},
                    "speaker": {"type": "string"},
                    "lines": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                    "chars_per_line": {"type": "array", "items": {"type": "integer", "minimum": 0}},
                    "cps": {"type": "number", "minimum": 0},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "flags": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "errors": {"type": "array"},
        "warnings": {"type": "array"},
    },
}

ERROR_SCHEMA = {
    "title": "RecoverableError",
    "type": "object",
    "required": ["job_id", "stage", "error"],
    "properties": {
        "job_id": {"type": "string"},
        "stage": {"type": "string"},
        "error": {
            "type": "object",
            "required": ["type", "code", "message", "missing_fields"],
            "properties": {
                "type": {"const": "recoverable_error"},
                "code": {"type": "string"},
                "message": {"type": "string"},
                "missing_fields": {"type": "array", "items": {"type": "string"}},
            },
        },
    },
}

SCHEMAS_BY_STAGE = {
    "TR-REPAIR": COMMON_SEGMENT_SCHEMA,
    "DIARIZE-MERGE": COMMON_SEGMENT_SCHEMA,
    "PUNC-NORM": COMMON_SEGMENT_SCHEMA,
    "PUNC-RESTORE": COMMON_SEGMENT_SCHEMA,
    "CASE-RESTORE": COMMON_SEGMENT_SCHEMA,
    "LANG-DETECT": COMMON_SEGMENT_SCHEMA,
    "TRANSLATE-SUB": COMMON_SEGMENT_SCHEMA,
    "SEGMENT-SUB": SUBTITLE_CUES_SCHEMA,
    "FORMAT-JSON": SUBTITLE_CUES_SCHEMA,
    "SCORE-QA": {
        "title": "QaReport",
        "type": "object",
        "required": ["job_id", "stage", "passed", "flags", "warnings"],
        "properties": {
            "job_id": {"type": "string"},
            "stage": {"const": "qa_report"},
            "passed": {"type": "boolean"},
            "flags": {"type": "array"},
            "warnings": {"type": "array"},
        },
    },
    "POST-EDIT": {
        "title": "PostEditSuggestions",
        "type": "object",
        "required": ["job_id", "stage", "edit_suggestions"],
        "properties": {
            "job_id": {"type": "string"},
            "stage": {"const": "post_edit_suggestions"},
            "edit_suggestions": {"type": "array"},
        },
    },
}
