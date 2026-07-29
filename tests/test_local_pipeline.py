import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from subtitle_automation.pipeline import segment_input_locally


class LocalPipelineTests(unittest.TestCase):
    def test_segment_input_locally_preserves_evidence_and_flags_uncertainty(self):
        job = {
            "job_id": "local-001",
            "source_language_hint": "en-US",
            "target_language": "en-US",
            "policies": {
                "max_chars_per_line": 12,
                "max_lines_per_cue": 2,
                "max_cps": 18,
                "allow_overlap": False,
            },
            "input_segments": [
                {
                    "segment_id": "s1",
                    "start_ms": 0,
                    "end_ms": 4000,
                    "speaker_candidates": ["SPK1"],
                    "asr_text": "we need maybe the red one no read run",
                    "confidence": 0.41,
                }
            ],
        }

        result = segment_input_locally(job)

        self.assertEqual(result["job_id"], "local-001")
        self.assertEqual(result["stage"], "subtitle_segmentation")
        self.assertGreater(len(result["subtitle_cues"]), 1)
        self.assertTrue(all(len(line) <= 12 for cue in result["subtitle_cues"] for line in cue["lines"]))
        self.assertIn("low_confidence", result["subtitle_cues"][0]["flags"])
        self.assertIn("we need", " ".join(" ".join(cue["lines"]) for cue in result["subtitle_cues"]))
        self.assertNotIn("red one means", " ".join(" ".join(cue["lines"]) for cue in result["subtitle_cues"]))


if __name__ == "__main__":
    unittest.main()
