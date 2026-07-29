import json
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from pathlib import Path

from subtitle_automation.web_jobs import WebJobManager
from subtitle_automation.web_server import (
    CaptionStudioServer,
    _bundled_static_dir,
    _default_workspace,
    _json_safe,
    _language_code,
)


class WebServerTests(unittest.TestCase):
    def test_distribution_contains_the_web_application(self):
        static_dir = _bundled_static_dir()
        self.assertIsNotNone(static_dir)
        self.assertTrue((static_dir / "index.html").is_file())

    def test_default_workspace_is_user_scoped(self):
        workspace = _default_workspace()
        self.assertTrue(workspace.is_absolute())
        self.assertIn(workspace.name, {"Caption Studio", "caption-studio"})

    def test_russian_language_code_is_supported(self):
        self.assertEqual(_language_code("ru-RU", default="auto"), "ru")

    def test_json_boundary_replaces_non_finite_numbers(self):
        self.assertEqual(_json_safe({"confidence": float("nan")}), {"confidence": None})

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        manager = WebJobManager(Path(self.tempdir.name))
        self.server = CaptionStudioServer(("127.0.0.1", 0), manager)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)

    def tearDown(self):
        self.connection.close()
        self.server.shutdown()
        self.server.server_close()
        self.tempdir.cleanup()

    def test_health_and_raw_media_upload(self):
        self.connection.request("GET", "/api/health")
        health_response = self.connection.getresponse()
        health = json.loads(health_response.read())
        self.assertEqual(health_response.status, 200)
        self.assertIn("ffmpeg", health)
        self.assertIn("mlx_whisper", health)
        self.assertIn("asr", health)
        self.assertIn("translator", health)
        self.assertEqual(health["version"], "0.5.1")
        self.assertEqual(health["translator"]["base_url"], "http://127.0.0.1:8000/v1")

        payload = b"fake-video-evidence"
        self.connection.request("POST", "/api/media?filename=sample.mp4", body=payload)
        upload_response = self.connection.getresponse()
        upload = json.loads(upload_response.read())
        self.assertEqual(upload_response.status, 201)
        self.assertEqual(upload["filename"], "sample.mp4")
        self.assertEqual(upload["size_bytes"], len(payload))
        self.assertEqual(len(upload["media_id"]), 32)

    def test_version_endpoint_matches_public_release_identity(self):
        self.connection.request("GET", "/api/version")
        response = self.connection.getresponse()
        payload = json.loads(response.read())
        self.assertEqual(response.status, 200)
        self.assertEqual(payload["repository"], "Caption_Studio")
        self.assertEqual(payload["version"], "0.5.1")
        self.assertEqual(payload["license"], "Apache-2.0")

    def test_upload_rejects_unsupported_extension(self):
        self.connection.request("POST", "/api/media?filename=notes.txt", body=b"nope")
        response = self.connection.getresponse()
        body = json.loads(response.read())
        self.assertEqual(response.status, 400)
        self.assertIn("영상만", body["error"])

    def test_health_supports_head_requests(self):
        self.connection.request("HEAD", "/api/health")
        response = self.connection.getresponse()
        self.assertEqual(response.status, 200)
        self.assertEqual(response.read(), b"")


if __name__ == "__main__":
    unittest.main()
