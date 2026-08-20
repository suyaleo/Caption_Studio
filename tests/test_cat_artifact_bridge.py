import hashlib
import json
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from pathlib import Path

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

    def restart_server(self):
        self.connection.close()
        self.server.shutdown()
        self.server.server_close()
        self.server = CaptionStudioServer(("127.0.0.1", 0), WebJobManager(self.root))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)

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


if __name__ == "__main__":
    unittest.main()
