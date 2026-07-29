import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from subtitle_automation.formats import cues_to_srt, cues_to_vtt
from subtitle_automation.validation import validate_subtitle_job


class SubtitleFormatAndValidationTests(unittest.TestCase):
    def test_formatters_emit_valid_srt_and_webvtt(self):
        cues = [
            {
                "cue_id": "c1",
                "start_ms": 0,
                "end_ms": 2200,
                "speaker": "SPK1",
                "lines": ["안녕하세요, 여러분.", "오늘 회의 시작하겠습니다."],
                "confidence": 0.87,
                "flags": [],
            },
            {
                "cue_id": "c2",
                "start_ms": 2250,
                "end_ms": 4700,
                "speaker": "SPK2",
                "lines": ["잠깐만요.", "데모 빌드가 아직 업로드 중이에요."],
                "confidence": 0.76,
                "flags": ["speaker_ambiguous"],
            },
        ]

        self.assertEqual(
            cues_to_srt(cues),
            "1\n"
            "00:00:00,000 --> 00:00:02,200\n"
            "안녕하세요, 여러분.\n"
            "오늘 회의 시작하겠습니다.\n\n"
            "2\n"
            "00:00:02,250 --> 00:00:04,700\n"
            "잠깐만요.\n"
            "데모 빌드가 아직 업로드 중이에요.\n",
        )
        self.assertEqual(
            cues_to_vtt(cues),
            "WEBVTT\n\n"
            "00:00:00.000 --> 00:00:02.200\n"
            "안녕하세요, 여러분.\n"
            "오늘 회의 시작하겠습니다.\n\n"
            "00:00:02.250 --> 00:00:04.700\n"
            "잠깐만요.\n"
            "데모 빌드가 아직 업로드 중이에요.\n",
        )

    def test_validation_flags_format_drift_and_policy_violations(self):
        result = {
            "job_id": "bad-001",
            "stage": "subtitle_segmentation",
            "subtitle_cues": [
                {
                    "cue_id": "c1",
                    "start_ms": 1000,
                    "end_ms": 900,
                    "speaker": "SPK1",
                    "lines": ["이 줄은 정책보다 확실히 너무 길어서 검수 플래그가 필요합니다."],
                    "confidence": 0.42,
                    "flags": [],
                },
                {
                    "cue_id": "c2",
                    "start_ms": 850,
                    "end_ms": 2200,
                    "speaker": "SPK1",
                    "lines": ["겹침"],
                    "confidence": 0.91,
                    "flags": [],
                },
            ],
        }
        policies = {
            "max_chars_per_line": 16,
            "max_lines_per_cue": 2,
            "max_cps": 10,
            "allow_overlap": False,
        }

        report = validate_subtitle_job(result, policies)
        codes = {flag["code"] for flag in report["flags"]}

        self.assertFalse(report["passed"])
        self.assertIn("timestamp_invalid", codes)
        self.assertIn("timestamp_not_monotonic", codes)
        self.assertIn("max_chars_per_line", codes)
        self.assertIn("max_cps", codes)
        self.assertIn("low_confidence", codes)

    def test_validation_fails_when_no_subtitle_cues_exist(self):
        report = validate_subtitle_job(
            {
                "job_id": "empty-001",
                "stage": "subtitle_segmentation",
                "subtitle_cues": [],
            },
            {"max_chars_per_line": 16, "max_lines_per_cue": 2, "max_cps": 15},
        )

        self.assertFalse(report["passed"])
        self.assertIn("missing_subtitle_cues", {flag["code"] for flag in report["flags"]})


if __name__ == "__main__":
    unittest.main()
