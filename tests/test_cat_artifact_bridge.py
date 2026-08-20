import hashlib
import json
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from pathlib import Path

from subtitle_automation.cat_bridge import CatArtifactBridge
from subtitle_automation.web_jobs import WebJobManager
from subtitle_automation.web_server import CaptionStudioServer


class CatArtifactBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.source = self.root / "scene.mp4"
        self.source.write_bytes(b"source-video-evidence")
        self.server = CaptionStudioServer(("127.0.0.1", 0), WebJobManager(self.root))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)

    def tearDown(self):
        self.connection.close()
        self.server.shutdown()
        self.server.server_close()
        self.tempdir.cleanup()

    def request(self, *, key="caption-job-1", prompt="첫 번째 자막", start_ms=2000, end_ms=4000):
        return {
            "protocolVersion": 1,
            "engineId": "caption-studio-bridge",
            "idempotencyKey": key,
            "capability": "generate-captions",
            "sceneId": "scene-2",
            "prompt": prompt,
            "parentArtifactId": "artifact-render-1",
            "inputPayloadUris": [self.source.as_uri()],
            "parameters": {"startMs": str(start_ms), "endMs": str(end_ms), "language": "ko"},
        }

    def post(self, payload):
        self.connection.request(
            "POST",
            "/cat/v1/artifacts",
            body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        response = self.connection.getresponse()
        return response.status, json.loads(response.read())

    def restart_server(self, bridge=None):
        self.connection.close()
        self.server.shutdown()
        self.server.server_close()
        self.server = CaptionStudioServer(
            ("127.0.0.1", 0),
            WebJobManager(self.root),
            cat_bridge=bridge,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)

    def asr_request(self, *, key="caption-asr-1", content_hash=None):
        return {
            "protocolVersion": 1,
            "engineId": "caption-studio-bridge",
            "idempotencyKey": key,
            "capability": "generate-captions",
            "sceneId": "scene-2",
            "prompt": "Transcribe the approved VoiceTrack",
            "parentArtifactId": "artifact-voice-approved",
            "inputPayloadUris": [self.source.as_uri()],
            "parameters": {
                "mode": "asr-v1",
                "captionSource": "asr",
                "provider": "faster-whisper",
                "model": "tiny",
                "language": "ko",
                "device": "cpu",
                "computeType": "int8",
                "wordTimestamps": "true",
                "inputContentHash": content_hash
                or f"sha256:{hashlib.sha256(self.source.read_bytes()).hexdigest()}",
                "startMs": "2000",
                "endMs": "4000",
                "timelineDurationMs": "6000",
            },
        }

    def install_asr_bridge(self, transcriber):
        bridge = CatArtifactBridge(
            self.root,
            asr_transcriber=transcriber,
            asr_status=lambda: {
                "available": True,
                "provider": "faster-whisper",
                "configured": "faster-whisper",
                "installed": {"mlx-whisper": False, "faster-whisper": True},
                "error": None,
            },
            media_prober=lambda _path: {
                "streams": [{"codec_type": "audio", "codec_name": "pcm_s16le"}],
                "format": {"duration": "2.000", "size": str(self.source.stat().st_size)},
            },
        )
        self.restart_server(bridge)
        return bridge

    def test_health_exposes_exact_bridge_contract(self):
        self.connection.request("GET", "/cat/v1/health")
        response = self.connection.getresponse()
        health = json.loads(response.read())
        self.assertEqual(response.status, 200)
        self.assertTrue(health["ok"])
        self.assertTrue(health["ready"])
        self.assertEqual(health["protocolVersion"], 1)
        self.assertEqual(health["engineId"], "caption-studio-bridge")
        self.assertEqual(health["capabilities"], ["generate-captions"])
        self.assertEqual(health["modes"], ["prompt-caption-v1", "asr-v1"])
        self.assertIn("asr", health)

    def test_result_is_downloadable_hash_verified_vtt(self):
        status, result = self.post(self.request())
        self.assertEqual(status, 200)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["output"]["mediaType"], "text/vtt")

        self.connection.request("GET", result["output"]["downloadUrl"])
        download = self.connection.getresponse()
        body = download.read()
        self.assertEqual(download.status, 200)
        self.assertEqual(download.getheader("Content-Type"), "text/vtt; charset=utf-8")
        self.assertEqual(
            result["output"]["contentHash"],
            f"sha256:{hashlib.sha256(body).hexdigest()}",
        )
        self.assertEqual(body.decode("utf-8"), "WEBVTT\n\n00:00:02.000 --> 00:00:04.000\n첫 번째 자막\n")

    def test_duplicate_request_reuses_one_output_and_receipt(self):
        first_status, first = self.post(self.request())
        second_status, second = self.post(self.request())
        self.assertEqual((first_status, second_status), (200, 200))
        self.assertEqual(first, second)
        bridge_root = self.root / "cat-artifact-bridge-v1"
        self.assertEqual(len(list((bridge_root / "outputs").glob("*.vtt"))), 1)
        self.assertEqual(len(list((bridge_root / "operations").glob("*.intent.json"))), 1)
        self.assertEqual(len(list((bridge_root / "operations").glob("*.receipt.json"))), 1)

    def test_server_restart_reuses_the_persisted_operation(self):
        first_status, first = self.post(self.request())
        self.restart_server()
        second_status, second = self.post(self.request())

        self.assertEqual((first_status, second_status), (200, 200))
        self.assertEqual(first, second)
        bridge_root = self.root / "cat-artifact-bridge-v1"
        self.assertEqual(len(list((bridge_root / "outputs").glob("*.vtt"))), 1)
        self.assertEqual(len(list((bridge_root / "operations").glob("*.receipt.json"))), 1)

    def test_reused_key_with_different_request_is_rejected(self):
        self.assertEqual(self.post(self.request())[0], 200)
        status, body = self.post(self.request(prompt="다른 자막"))
        self.assertEqual(status, 409)
        self.assertIn("different request", body["error"])

    def test_tampered_output_is_not_silently_reused(self):
        status, result = self.post(self.request())
        self.assertEqual(status, 200)
        filename = result["output"]["downloadUrl"].rsplit("/", 1)[-1]
        (self.root / "cat-artifact-bridge-v1" / "outputs" / filename).write_bytes(b"tampered")
        status, body = self.post(self.request())
        self.assertEqual(status, 409)
        self.assertIn("does not match", body["error"])

    def test_invalid_contract_or_missing_input_is_rejected(self):
        wrong_engine = self.request()
        wrong_engine["engineId"] = "not-caption-studio"
        self.assertEqual(self.post(wrong_engine)[0], 400)
        missing = self.request(key="missing-input")
        missing["inputPayloadUris"] = [(self.root / "missing.mp4").as_uri()]
        self.assertEqual(self.post(missing)[0], 400)

    def test_asr_mode_records_provider_and_reuses_complete_checkpoints(self):
        calls = []

        def transcribe(_path, _model, **options):
            calls.append(options)
            first = {
                "start": 0.0,
                "end": 0.8,
                "text": "첫 자막",
                "avg_logprob": -0.1,
                "no_speech_prob": 0.01,
                "words": [{"start": 0.0, "end": 0.8, "word": "첫 자막", "probability": 0.9}],
            }
            second = {
                "start": 1.0,
                "end": 1.8,
                "text": "둘째 자막",
                "avg_logprob": -0.2,
                "no_speech_prob": 0.01,
            }
            options["on_segment"](first)
            options["on_segment"](second)
            return {
                "_provider": "faster-whisper",
                "language": "ko",
                "segments": [first, second],
            }

        self.install_asr_bridge(transcribe)
        first_status, first = self.post(self.asr_request())
        second_status, second = self.post(self.asr_request())

        self.assertEqual((first_status, second_status), (200, 200))
        self.assertEqual(first, second)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["provider"], "faster-whisper")
        self.assertTrue(calls[0]["word_timestamps"])
        self.assertEqual(first["provenance"]["mode"], "asr-v1")
        self.assertEqual(first["provenance"]["provider"], "faster-whisper")

        self.connection.request("GET", first["output"]["downloadUrl"])
        body = self.connection.getresponse().read().decode("utf-8")
        self.assertIn("00:00:02.000 --> 00:00:02.800", body)
        self.assertIn("00:00:03.000 --> 00:00:03.800", body)
        operations = self.root / "cat-artifact-bridge-v1" / "operations"
        self.assertEqual(len(list(operations.glob("*.asr.complete.json"))), 1)
        self.assertEqual(len(list(operations.glob("*.cues.json"))), 1)

    def test_asr_interruption_resumes_from_partial_segment_after_server_restart(self):
        calls = []

        def transcribe(_path, _model, **options):
            calls.append(options["clip_timestamps"])
            if len(calls) == 1:
                options["on_segment"](
                    {
                        "start": 0.0,
                        "end": 1.0,
                        "text": "복구 전",
                        "avg_logprob": -0.1,
                        "no_speech_prob": 0.0,
                    }
                )
                raise RuntimeError("simulated ASR interruption")
            segment = {
                "start": 1.1,
                "end": 1.8,
                "text": "복구 후",
                "avg_logprob": -0.1,
                "no_speech_prob": 0.0,
            }
            options["on_segment"](segment)
            return {"_provider": "faster-whisper", "language": "ko", "segments": [segment]}

        self.install_asr_bridge(transcribe)
        failed_status, failed = self.post(self.asr_request(key="caption-asr-resume"))
        self.assertEqual(failed_status, 500)
        self.assertIn("simulated ASR interruption", failed["error"])

        self.install_asr_bridge(transcribe)
        status, result = self.post(self.asr_request(key="caption-asr-resume"))
        self.assertEqual(status, 200)
        self.assertEqual(calls, ["0", "1.000"])
        self.assertTrue(result["provenance"]["partialCheckpointRecovered"])

        self.connection.request("GET", result["output"]["downloadUrl"])
        body = self.connection.getresponse().read().decode("utf-8")
        self.assertIn("복구 전", body)
        self.assertIn("복구 후", body)

        slug = hashlib.sha256("caption-asr-resume".encode()).hexdigest()
        operations = self.root / "cat-artifact-bridge-v1" / "operations"
        (operations / f"{slug}.receipt.json").unlink()
        recovered_status, recovered = self.post(self.asr_request(key="caption-asr-resume"))
        self.assertEqual(recovered_status, 200)
        self.assertTrue(recovered["provenance"]["partialCheckpointRecovered"])
        self.assertEqual(calls, ["0", "1.000"])

    def test_asr_input_hash_mismatch_is_rejected_before_transcription(self):
        calls = []

        def transcribe(*_args, **_kwargs):
            calls.append(True)
            return {}

        self.install_asr_bridge(transcribe)
        status, body = self.post(
            self.asr_request(
                key="caption-asr-hash-mismatch",
                content_hash=f"sha256:{'0' * 64}",
            )
        )
        self.assertEqual(status, 409)
        self.assertIn("input hash mismatch", body["error"])
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
