import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from subtitle_automation.translation import TranslationClient, TranslationConfig, _format_caption


class _FakeOMLXHandler(BaseHTTPRequestHandler):
    requests = []
    models = ["test-local-model"]
    drop_last_above = 0
    blank_last_above = 0
    long_last_above = 0

    def do_GET(self):  # noqa: N802
        self._json({"object": "list", "data": [{"id": model} for model in self.__class__.models]})

    def do_POST(self):  # noqa: N802
        length = int(self.headers["Content-Length"])
        payload = json.loads(self.rfile.read(length))
        self.__class__.requests.append(payload)
        user_payload = json.loads(payload["messages"][1]["content"])
        if user_payload.get("task") == "shorten_video_caption":
            self._json({"choices": [{"message": {"content": '["짧게 다듬은 번역"]'}}]})
            return
        captions = user_payload["captions"]
        translated = [f"번역 {item}" for item in captions]
        if self.__class__.drop_last_above and len(translated) > self.__class__.drop_last_above:
            translated = translated[:-1]
        if self.__class__.blank_last_above and len(translated) > self.__class__.blank_last_above:
            translated[-1] = ""
        if self.__class__.long_last_above and len(translated) > self.__class__.long_last_above:
            translated[-1] = "아주 긴 번역 문장입니다 " * 8
        self._json({"choices": [{"message": {"content": f"```json\n{json.dumps(translated, ensure_ascii=False)}\n```"}}]})

    def _json(self, payload):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format, *args):
        pass


class TranslationTests(unittest.TestCase):
    def setUp(self):
        _FakeOMLXHandler.requests = []
        _FakeOMLXHandler.models = ["test-local-model"]
        _FakeOMLXHandler.drop_last_above = 0
        _FakeOMLXHandler.blank_last_above = 0
        _FakeOMLXHandler.long_last_above = 0
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeOMLXHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.config = TranslationConfig(
            base_url=f"http://127.0.0.1:{self.server.server_port}/v1",
            batch_size=2,
            context_size=2,
            retries=1,
        )

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def test_health_discovers_omlx_model(self):
        health = TranslationClient(self.config).health()
        self.assertTrue(health["available"])
        self.assertEqual(health["model"], "test-local-model")

    def test_health_requires_a_loaded_model(self):
        _FakeOMLXHandler.models = []
        health = TranslationClient(self.config).health()
        self.assertFalse(health["available"])
        self.assertIn("로드된 모델", health["error"])

    def test_health_rejects_configured_model_that_is_not_loaded(self):
        config = TranslationConfig(
            base_url=self.config.base_url,
            model="missing-model",
            retries=1,
        )
        health = TranslationClient(config).health()
        self.assertFalse(health["available"])

    def test_translation_batches_preserve_count_and_context(self):
        translated, metadata = TranslationClient(self.config).translate(
            ["하나", "둘", "셋"],
            source_language="ja",
            target_language="ko",
        )
        self.assertEqual(translated, ["번역 하나", "번역 둘", "번역 셋"])
        self.assertEqual(metadata["model"], "test-local-model")
        self.assertEqual(len(_FakeOMLXHandler.requests), 2)
        second_user = json.loads(_FakeOMLXHandler.requests[1]["messages"][1]["content"])
        self.assertEqual(second_user["previous_translated_context"], ["번역 하나", "번역 둘"])

    def test_translation_splits_batch_when_model_omits_an_item(self):
        _FakeOMLXHandler.drop_last_above = 2
        config = TranslationConfig(
            base_url=self.config.base_url,
            batch_size=10,
            context_size=2,
            retries=1,
        )
        translated, _metadata = TranslationClient(config).translate(
            ["하나", "둘", "셋", "넷"],
            source_language="ja",
            target_language="ko",
        )
        self.assertEqual(translated, ["번역 하나", "번역 둘", "번역 셋", "번역 넷"])
        self.assertEqual(len(_FakeOMLXHandler.requests), 3)

    def test_translation_splits_batch_when_model_returns_blank_item(self):
        _FakeOMLXHandler.blank_last_above = 2
        config = TranslationConfig(
            base_url=self.config.base_url,
            batch_size=10,
            context_size=2,
            retries=1,
        )
        translated, _metadata = TranslationClient(config).translate(
            ["하나", "둘", "셋", "넷"],
            source_language="ru",
            target_language="ko",
        )
        self.assertEqual(translated, ["번역 하나", "번역 둘", "번역 셋", "번역 넷"])

    def test_long_caption_is_limited_to_two_lines(self):
        source = "이 문장은 화면 한 줄에 길어서 두 줄로 자연스럽게 나뉘어야 합니다"
        formatted = _format_caption(source)
        self.assertLessEqual(len(formatted.splitlines()), 2)
        self.assertTrue(all(len(line) <= 23 for line in formatted.splitlines()))
        self.assertEqual(formatted.replace("\n", " "), source)

    def test_translation_compresses_overlong_item_without_truncation(self):
        _FakeOMLXHandler.long_last_above = 2
        config = TranslationConfig(
            base_url=self.config.base_url,
            batch_size=10,
            context_size=2,
            retries=1,
        )
        translated, _metadata = TranslationClient(config).translate(
            ["하나", "둘", "셋", "넷"],
            source_language="zh",
            target_language="ko",
        )
        self.assertEqual(translated, ["번역 하나", "번역 둘", "번역 셋", "짧게 다듬은 번역"])
        shorten_payload = json.loads(_FakeOMLXHandler.requests[-1]["messages"][1]["content"])
        self.assertEqual(shorten_payload["task"], "shorten_video_caption")
        self.assertEqual(shorten_payload["max_characters_including_spaces"], 46)


if __name__ == "__main__":
    unittest.main()
