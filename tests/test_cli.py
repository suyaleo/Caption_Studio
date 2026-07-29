import json
import io
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


class CliTests(unittest.TestCase):
    def test_cli_segments_validates_and_formats_sample_job(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            job_path = tmp / "job.json"
            cues_path = tmp / "cues.json"
            qa_path = tmp / "qa.json"
            srt_path = tmp / "demo.srt"
            job_path.write_text(
                json.dumps(
                    {
                        "job_id": "cli-001",
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
                                "asr_text": "안녕하세요 여러분 오늘 회의 시작하겠습니다",
                                "confidence": 0.87,
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
            self._run(["segment-local", "--input", str(job_path), "--output", str(cues_path)], env)
            self._run(["validate", "--input", str(cues_path), "--policies", str(job_path), "--output", str(qa_path)], env)
            self._run(["format-srt", "--input", str(cues_path), "--output", str(srt_path)], env)

            cues = json.loads(cues_path.read_text(encoding="utf-8"))
            qa = json.loads(qa_path.read_text(encoding="utf-8"))
            srt = srt_path.read_text(encoding="utf-8")
            self.assertEqual(cues["stage"], "subtitle_segmentation")
            self.assertTrue(qa["passed"])
            self.assertIn("00:00:00,000 --> 00:00:02,200", srt)
            self.assertIn("안녕하세요 여러분", srt)

    def test_cli_llm_stage_writes_raw_response_and_fallback_result(self):
        from subtitle_automation import cli

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            job_path = tmp / "job.json"
            result_path = tmp / "llm_cues.json"
            raw_path = tmp / "raw.json"
            job_path.write_text(
                json.dumps(
                    {
                        "job_id": "cli-llm-001",
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
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            fake_client = _FakeCLIClient("Here's a thinking process:\n\n1. Not JSON.")
            with patch("subtitle_automation.cli.LocalLLMClient", return_value=fake_client):
                rc = cli.main(
                    [
                        "llm-stage",
                        "--stage",
                        "SEGMENT-SUB",
                        "--input",
                        str(job_path),
                        "--output",
                        str(result_path),
                        "--raw-output",
                        str(raw_path),
                        "--fallback",
                        "local",
                    ]
                )

            self.assertEqual(rc, 0)
            result = json.loads(result_path.read_text(encoding="utf-8"))
            raw = json.loads(raw_path.read_text(encoding="utf-8"))
            self.assertEqual(result["llm_metadata"]["fallback"], "local")
            self.assertEqual(raw["id"], "chatcmpl-cli-test")

    def test_cli_run_all_writes_complete_deliverable_set(self):
        from subtitle_automation import cli

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            job_path = tmp / "job.json"
            out_dir = tmp / "run"
            payload = {
                "job_id": "run-001",
                "stage": "subtitle_segmentation",
                "source_language": "ko-KR",
                "target_language": "ko-KR",
                "subtitle_cues": [
                    {
                        "cue_id": "c1",
                        "start_ms": 0,
                        "end_ms": 2200,
                        "speaker": "SPK1",
                        "lines": ["안녕하세요, 여러분.", "오늘 회의 시작하겠습니다."],
                        "chars_per_line": [11, 14],
                        "cps": 11.8,
                        "confidence": 0.87,
                        "flags": [],
                    }
                ],
                "errors": [],
                "warnings": [],
            }
            job_path.write_text(
                json.dumps(
                    {
                        "job_id": "run-001",
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
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            fake_client = _FakeCLIClient(json.dumps(payload, ensure_ascii=False))
            with patch("subtitle_automation.cli.LocalLLMClient", return_value=fake_client):
                with redirect_stdout(io.StringIO()):
                    rc = cli.main(
                        [
                            "run-all",
                            "--input",
                            str(job_path),
                            "--output-dir",
                            str(out_dir),
                            "--mode",
                            "llm",
                            "--max-tokens",
                            "512",
                        ]
                    )

            self.assertEqual(rc, 0)
            expected = [
                out_dir / "prompts" / "segment_sub_prompt.json",
                out_dir / "reports" / "local_llm_raw.json",
                out_dir / "subtitles" / "cues.json",
                out_dir / "reports" / "qa.json",
                out_dir / "subtitles" / "output.srt",
                out_dir / "subtitles" / "output.vtt",
                out_dir / "reports" / "manifest.json",
                out_dir / "reports" / "acceptance.md",
            ]
            for path in expected:
                self.assertTrue(path.exists(), f"missing {path}")

            manifest = json.loads((out_dir / "reports" / "manifest.json").read_text(encoding="utf-8"))
            qa = json.loads((out_dir / "reports" / "qa.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "passed")
            self.assertEqual(manifest["mode"], "llm")
            self.assertTrue(manifest["artifacts"]["srt"].endswith("subtitles/output.srt"))
            self.assertTrue(qa["passed"])
            self.assertIn("00:00:00,000 --> 00:00:02,200", (out_dir / "subtitles" / "output.srt").read_text(encoding="utf-8"))

    def test_cli_run_all_falls_back_when_llm_json_fails_qa(self):
        from subtitle_automation import cli

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            job_path = tmp / "job.json"
            out_dir = tmp / "run"
            empty_payload = {
                "job_id": "run-fallback-001",
                "stage": "subtitle_segmentation",
                "source_language": "ko-KR",
                "target_language": "ko-KR",
                "subtitle_cues": [],
                "errors": [],
                "warnings": [],
            }
            job_path.write_text(
                json.dumps(
                    {
                        "job_id": "run-fallback-001",
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
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            fake_client = _FakeCLIClient(json.dumps(empty_payload, ensure_ascii=False))
            with patch("subtitle_automation.cli.LocalLLMClient", return_value=fake_client):
                with redirect_stdout(io.StringIO()):
                    rc = cli.main(
                        [
                            "run-all",
                            "--input",
                            str(job_path),
                            "--output-dir",
                            str(out_dir),
                            "--mode",
                            "llm",
                            "--fallback",
                            "local",
                        ]
                    )

            self.assertEqual(rc, 0)
            result = json.loads((out_dir / "subtitles" / "cues.json").read_text(encoding="utf-8"))
            manifest = json.loads((out_dir / "reports" / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(result["llm_metadata"]["fallback"], "local_after_qa")
            self.assertEqual(manifest["status"], "passed")
            self.assertEqual(manifest["llm"]["fallback"], "local_after_qa")

    def test_cli_prepare_mp4_input_writes_run_all_job_from_asr_json(self):
        from subtitle_automation import cli

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            media_path = tmp / "sample.mp4"
            asr_path = tmp / "asr.json"
            probe_path = tmp / "probe.json"
            output_path = tmp / "input_job.json"
            media_path.write_bytes(b"fake mp4 for conversion-only test")
            asr_path.write_text(
                json.dumps(
                    {
                        "language": "ko",
                        "segments": [
                            {
                                "start": 0.0,
                                "end": 1.2,
                                "text": " 자동 자막 테스트 ",
                                "avg_logprob": -0.10536051565782628,
                                "no_speech_prob": 0.01,
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            probe_path.write_text(
                json.dumps(
                    {
                        "streams": [{"codec_type": "audio", "codec_name": "aac", "duration": "1.200000"}],
                        "format": {"duration": "1.200000", "size": "27"},
                    }
                ),
                encoding="utf-8",
            )

            with redirect_stdout(io.StringIO()):
                rc = cli.main(
                    [
                        "prepare-mp4-input",
                        "--media",
                        str(media_path),
                        "--asr-json",
                        str(asr_path),
                        "--media-probe-json",
                        str(probe_path),
                        "--output",
                        str(output_path),
                        "--job-id",
                        "prepared-001",
                        "--asr-model",
                        "mlx-community/whisper-small-mlx",
                    ]
                )

            self.assertEqual(rc, 0)
            job = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(job["job_id"], "prepared-001")
            self.assertEqual(job["source_media"]["path"], str(media_path))
            self.assertEqual(job["input_segments"][0]["text"], "자동 자막 테스트")
            self.assertEqual(job["input_segments"][0]["confidence"], 0.9)

    def test_cli_run_media_writes_preparation_run_all_and_review_report(self):
        from subtitle_automation import cli

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            media_path = tmp / "sample.mp4"
            asr_path = tmp / "asr.json"
            probe_path = tmp / "probe.json"
            output_dir = tmp / "media_run"
            media_path.write_bytes(b"fake mp4 for conversion-only test")
            asr_path.write_text(
                json.dumps(
                    {
                        "language": "ko",
                        "segments": [
                            {
                                "start": 0.0,
                                "end": 1.8,
                                "text": "자동 실행 검수입니다.",
                                "avg_logprob": -0.10536051565782628,
                                "no_speech_prob": 0.01,
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            probe_path.write_text(
                json.dumps(
                    {
                        "streams": [
                            {"codec_type": "video", "codec_name": "h264", "width": 1280, "height": 720},
                            {"codec_type": "audio", "codec_name": "aac", "duration": "1.800000"},
                        ],
                        "format": {"duration": "1.800000", "size": "27"},
                    }
                ),
                encoding="utf-8",
            )

            with redirect_stdout(io.StringIO()):
                rc = cli.main(
                    [
                        "run-media",
                        "--media",
                        str(media_path),
                        "--asr-json",
                        str(asr_path),
                        "--media-probe-json",
                        str(probe_path),
                        "--output-dir",
                        str(output_dir),
                        "--job-id",
                        "media-run-001",
                        "--mode",
                        "local",
                    ]
                )

            self.assertEqual(rc, 0)
            expected = [
                output_dir / "input_job.json",
                output_dir / "run_all" / "reports" / "manifest.json",
                output_dir / "run_all" / "reports" / "qa.json",
                output_dir / "run_all" / "subtitles" / "output.srt",
                output_dir / "run_all" / "subtitles" / "output.vtt",
                output_dir / "review_report.md",
            ]
            for path in expected:
                self.assertTrue(path.exists(), f"missing {path}")

            manifest = json.loads((output_dir / "run_all" / "reports" / "manifest.json").read_text(encoding="utf-8"))
            qa = json.loads((output_dir / "run_all" / "reports" / "qa.json").read_text(encoding="utf-8"))
            review = (output_dir / "review_report.md").read_text(encoding="utf-8")
            self.assertEqual(manifest["status"], "passed")
            self.assertTrue(qa["passed"])
            self.assertIn("## Review Verdict", review)
            self.assertIn("release-ready", review)

    def _run(self, args, env):
        completed = subprocess.run(
            [sys.executable, "-m", "subtitle_automation.cli", *args],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            self.fail(f"CLI failed: {completed.stderr}\nSTDOUT:\n{completed.stdout}")


if __name__ == "__main__":
    unittest.main()


class _FakeCLIClient:
    base_url = "http://127.0.0.1:8000/v1"
    model = "Ornith-1.0-35B-8bit"

    def __init__(self, content):
        self.content = content

    def chat(self, messages, max_tokens):
        return {
            "id": "chatcmpl-cli-test",
            "object": "chat.completion",
            "model": self.model,
            "choices": [
                {
                    "message": {"role": "assistant", "content": self.content},
                    "finish_reason": "stop",
                }
            ],
        }
