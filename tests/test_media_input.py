import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


from subtitle_automation.media_input import (
    asr_provider_status,
    build_input_job_from_asr,
    faster_whisper_model_name,
    normalize_asr_model,
)


class MediaInputTests(unittest.TestCase):
    def test_docker_model_aliases_map_to_faster_whisper_presets(self):
        self.assertEqual(faster_whisper_model_name("mlx-community/whisper-small-mlx"), "small")
        self.assertEqual(faster_whisper_model_name("mlx-community/whisper-large-v3-turbo"), "turbo")

    @patch("subtitle_automation.media_input.importlib.util.find_spec")
    @patch.dict("os.environ", {"CAPTION_ASR_PROVIDER": "faster-whisper"}, clear=False)
    def test_asr_status_selects_docker_provider(self, find_spec):
        find_spec.side_effect = lambda name: object() if name == "faster_whisper" else None
        status = asr_provider_status()
        self.assertTrue(status["available"])
        self.assertEqual(status["provider"], "faster-whisper")

    def test_legacy_small_model_name_resolves_to_public_mlx_repository(self):
        self.assertEqual(
            normalize_asr_model("mlx-community/whisper-small"),
            "mlx-community/whisper-small-mlx",
        )

    def test_build_input_job_from_asr_preserves_media_and_confidence_evidence(self):
        asr = {
            "language": "ko",
            "segments": [
                {
                    "start": 0.0,
                    "end": 1.5,
                    "text": " 안녕하세요 ",
                    "avg_logprob": math.log(0.82),
                    "no_speech_prob": 0.01,
                }
            ],
        }
        probe = {
            "streams": [
                {
                    "index": 0,
                    "codec_name": "h264",
                    "codec_type": "video",
                    "width": 1920,
                    "height": 1080,
                    "duration": "2.000000",
                },
                {
                    "index": 1,
                    "codec_name": "aac",
                    "codec_type": "audio",
                    "duration": "2.000000",
                },
            ],
            "format": {"duration": "2.000000", "size": "1234"},
        }

        job = build_input_job_from_asr(
            media_path=Path("/tmp/sample.mp4"),
            asr_result=asr,
            media_probe=probe,
            job_id="media-001",
            asr_model="mlx-community/whisper-small-mlx",
        )

        self.assertEqual(job["job_id"], "media-001")
        self.assertEqual(job["source_language_hint"], "ko-KR")
        self.assertEqual(job["target_language"], "ko-KR")
        self.assertEqual(job["source_media"]["path"], "/tmp/sample.mp4")
        self.assertEqual(job["source_media"]["duration_seconds"], 2.0)
        self.assertEqual(job["source_media"]["video"]["width"], 1920)
        self.assertEqual(job["source_media"]["audio"]["codec_name"], "aac")
        self.assertEqual(job["input_segments"][0]["segment_id"], "asr-001")
        self.assertEqual(job["input_segments"][0]["start_ms"], 0)
        self.assertEqual(job["input_segments"][0]["end_ms"], 1500)
        self.assertEqual(job["input_segments"][0]["text"], "안녕하세요")
        self.assertEqual(job["input_segments"][0]["confidence"], 0.82)
        self.assertNotIn("low_confidence_asr", job["input_segments"][0]["flags"])

    def test_build_input_job_from_asr_flags_low_confidence_without_inflating_it(self):
        asr = {
            "language": "ko",
            "segments": [
                {
                    "start": 0.0,
                    "end": 1.0,
                    "text": "불확실한 문장",
                    "avg_logprob": math.log(0.5),
                    "no_speech_prob": 0.02,
                }
            ],
        }

        job = build_input_job_from_asr(
            media_path=Path("/tmp/low.mp4"),
            asr_result=asr,
            media_probe={"streams": [], "format": {"duration": "1.000000", "size": "10"}},
            job_id="media-low",
            asr_model="mlx-community/whisper-tiny",
        )

        segment = job["input_segments"][0]
        self.assertEqual(segment["confidence"], 0.5)
        self.assertIn("low_confidence_asr", segment["flags"])

    def test_build_input_job_filters_invalid_segments_and_normalizes_nan_confidence(self):
        asr = {
            "language": "ko",
            "segments": [
                {"start": 1.0, "end": 1.0, "text": "잘못된 타임스탬프", "avg_logprob": -0.1},
                {"start": 1.0, "end": 2.0, "text": "   ", "avg_logprob": -0.1},
                {"start": 2.0, "end": 3.0, "text": "확인 필요", "avg_logprob": math.nan},
            ],
        }

        job = build_input_job_from_asr(
            media_path=Path("/tmp/sample.mp4"),
            asr_result=asr,
            media_probe={"streams": [], "format": {"duration": "3.000000", "size": "10"}},
            job_id="media-invalid",
            asr_model="mlx-community/whisper-small-mlx",
        )

        self.assertEqual(len(job["input_segments"]), 1)
        segment = job["input_segments"][0]
        self.assertEqual(segment["confidence"], 0.0)
        self.assertIn("asr_confidence_unavailable", segment["flags"])
        self.assertIn("low_confidence_asr", segment["flags"])


if __name__ == "__main__":
    unittest.main()
