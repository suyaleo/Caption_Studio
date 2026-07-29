import json
import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from subtitle_automation.prompts import build_prompt_job


class PromptContractTests(unittest.TestCase):
    def test_segment_prompt_uses_core_wrapper_schema_and_medium_effort(self):
        job = {
            "job_id": "demo-001",
            "ui_language": "ko-KR",
            "source_language_hint": "unknown",
            "target_language": "ko-KR",
            "content_profile": {
                "single_speaker": False,
                "multi_speaker": True,
                "noisy_audio": True,
                "music_background": False,
                "code_switching": True,
                "clip_length_seconds": 18,
            },
            "policies": {
                "clean_reading_mode": True,
                "redaction_mode": "flag_only",
                "profanity_mode": "preserve",
                "max_chars_per_line": 16,
                "max_lines_per_cue": 2,
                "max_cps": 15,
                "allow_overlap": False,
            },
            "input_segments": [
                {
                    "segment_id": "s1",
                    "start_ms": 0,
                    "end_ms": 2200,
                    "speaker_candidates": ["SPK1"],
                    "asr_text": "annyeong haseyo everyone today meeting starts now",
                    "confidence": 0.78,
                }
            ],
        }

        bundle = build_prompt_job("SEGMENT-SUB", job)

        self.assertEqual(bundle["stage"], "SEGMENT-SUB")
        self.assertEqual(bundle["recommended_effort"], "medium")
        self.assertIn("Do not invent words", bundle["system_prompt"])
        self.assertIn("<non_hallucination_policy>", bundle["system_prompt"])
        self.assertIn("<stage>SEGMENT-SUB</stage>", bundle["user_prompt"])
        self.assertIn("<target_language>ko-KR</target_language>", bundle["user_prompt"])
        self.assertIn("<output_schema>", bundle["user_prompt"])
        self.assertEqual(bundle["output_schema"]["title"], "SubtitleCues")

        parsed_segments = json.loads(
            bundle["user_prompt"].split("<input_segments>", 1)[1].split("</input_segments>", 1)[0].strip()
        )
        self.assertEqual(parsed_segments[0]["segment_id"], "s1")


if __name__ == "__main__":
    unittest.main()
