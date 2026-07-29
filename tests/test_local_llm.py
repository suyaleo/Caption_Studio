import json
import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from subtitle_automation.llm_pipeline import run_stage_with_local_llm
from subtitle_automation.local_llm import extract_json_payload


class FakeLLMClient:
    def __init__(self, content):
        self.content = content
        self.calls = []
        self.model = "Ornith-1.0-35B-8bit"
        self.base_url = "http://127.0.0.1:8000/v1"

    def chat(self, messages, max_tokens):
        self.calls.append({"messages": messages, "max_tokens": max_tokens})
        return {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "model": self.model,
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": self.content,
                    },
                    "finish_reason": "stop",
                }
            ],
        }


class LocalLLMTests(unittest.TestCase):
    def test_extract_json_payload_accepts_fenced_or_prefixed_json(self):
        content = """Here's a thinking process:

```json
{"job_id":"demo","stage":"subtitle_segmentation","subtitle_cues":[]}
```
"""

        parsed = extract_json_payload(content)

        self.assertEqual(parsed["job_id"], "demo")
        self.assertEqual(parsed["stage"], "subtitle_segmentation")

    def test_llm_stage_uses_parsed_json_when_model_returns_valid_payload(self):
        payload = {
            "job_id": "llm-001",
            "stage": "subtitle_segmentation",
            "source_language": "ko-KR",
            "target_language": "ko-KR",
            "subtitle_cues": [],
            "errors": [],
            "warnings": [],
        }
        client = FakeLLMClient(json.dumps(payload, ensure_ascii=False))

        result, raw = run_stage_with_local_llm("SEGMENT-SUB", self._job(), client=client, fallback="none")

        self.assertEqual(result["job_id"], "llm-001")
        self.assertEqual(result["llm_metadata"]["parsed"], True)
        self.assertEqual(raw["model"], "Ornith-1.0-35B-8bit")
        self.assertEqual(client.calls[0]["messages"][0]["role"], "system")
        self.assertIn("first non-whitespace character must be {", client.calls[0]["messages"][1]["content"])

    def test_llm_stage_normalizes_job_id_drift_from_model_output(self):
        payload = {
            "job_id": "seg-001",
            "stage": "subtitle_segmentation",
            "source_language": "ko-KR",
            "target_language": "ko-KR",
            "subtitle_cues": [],
            "errors": [],
            "warnings": [],
        }
        client = FakeLLMClient(json.dumps(payload, ensure_ascii=False))

        result, _ = run_stage_with_local_llm("SEGMENT-SUB", self._job(), client=client, fallback="none")

        self.assertEqual(result["job_id"], "llm-001")
        self.assertIn("local_llm_job_id_normalized", result["warnings"])

    def test_llm_stage_repairs_cues_that_exceed_max_lines_policy(self):
        payload = {
            "job_id": "llm-001",
            "stage": "subtitle_segmentation",
            "source_language": "ko-KR",
            "target_language": "ko-KR",
            "subtitle_cues": [
                {
                    "cue_id": "cue_s1",
                    "start_ms": 0,
                    "end_ms": 3000,
                    "speaker": "SPK1",
                    "lines": ["첫 줄", "둘째 줄", "셋째 줄"],
                    "chars_per_line": [3, 4, 4],
                    "cps": 3.66,
                    "confidence": 0.9,
                    "flags": [],
                }
            ],
            "errors": [],
            "warnings": [],
        }
        client = FakeLLMClient(json.dumps(payload, ensure_ascii=False))

        result, _ = run_stage_with_local_llm("SEGMENT-SUB", self._job(), client=client, fallback="none")

        self.assertEqual(len(result["subtitle_cues"]), 2)
        self.assertTrue(all(len(cue["lines"]) <= 2 for cue in result["subtitle_cues"]))
        self.assertIn("local_llm_cue_policy_repaired", result["warnings"])

    def test_llm_stage_falls_back_locally_when_model_returns_non_json(self):
        client = FakeLLMClient("Here's a thinking process:\n\n1. I should explain instead of JSON.")

        result, raw = run_stage_with_local_llm("SEGMENT-SUB", self._job(), client=client, fallback="local")

        self.assertEqual(result["stage"], "subtitle_segmentation")
        self.assertGreater(len(result["subtitle_cues"]), 0)
        self.assertEqual(result["llm_metadata"]["parsed"], False)
        self.assertEqual(result["llm_metadata"]["fallback"], "local")
        self.assertIn("local_llm_invalid_json_fallback_used", result["warnings"])
        self.assertEqual(raw["id"], "chatcmpl-test")

    def _job(self):
        return {
            "job_id": "llm-001",
            "source_language_hint": "ko-KR",
            "target_language": "ko-KR",
            "policies": {
                "max_chars_per_line": 16,
                "max_lines_per_cue": 2,
                "max_cps": 20,
                "allow_overlap": False,
            },
            "input_segments": [
                {
                    "segment_id": "s1",
                    "start_ms": 0,
                    "end_ms": 2200,
                    "speaker_candidates": ["SPK1"],
                    "text": "안녕하세요, 여러분. 오늘 회의 시작하겠습니다.",
                    "confidence": 0.87,
                }
            ],
        }


if __name__ == "__main__":
    unittest.main()
