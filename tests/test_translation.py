import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from subtitle_automation.translation import TranslationClient, TranslationConfig, _format_caption


class TranslationTests(unittest.TestCase):
    def setUp(self):
        self.commands: list[list[str]] = []
        self._auth_directory = tempfile.TemporaryDirectory()
        self.auth_root = Path(self._auth_directory.name) / "auth"

    def tearDown(self):
        self._auth_directory.cleanup()

    def _runner(self, command, _environment, _timeout):
        self.commands.append(command)
        if command[:2] == ["grok", "models"] or command[:3] == ["codex", "login", "status"]:
            return subprocess.CompletedProcess(command, 0, "ready", "")
        if command[0] == "grok":
            return subprocess.CompletedProcess(command, 0, '["번역 하나", "번역 둘"]', "")
        output_index = command.index("--output-last-message") + 1
        Path(command[output_index]).write_text('["번역 하나", "번역 둘"]', encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    @patch("subtitle_automation.translation.shutil.which", return_value="/usr/local/bin/provider")
    def test_grok_health_and_translation_use_isolated_cli(self, _which):
        config = TranslationConfig(provider="grok", auth_root=self.auth_root, batch_size=2, retries=1)
        credential = self.auth_root / "grok" / ".grok" / "auth.json"
        credential.parent.mkdir(parents=True)
        credential.write_text("{}", encoding="utf-8")
        client = TranslationClient(config, runner=self._runner)
        self.assertTrue(client.health()["available"])
        translated, metadata = client.translate(["one", "two"], source_language="en", target_language="ko")
        self.assertEqual(translated, ["번역 하나", "번역 둘"])
        self.assertEqual(metadata["provider"], "grok")
        self.assertEqual(self.commands[0], ["grok", "models"])
        self.assertTrue(any(command[0] == "grok" and "-p" in command for command in self.commands))

    @patch("subtitle_automation.translation.shutil.which", return_value="/usr/local/bin/provider")
    def test_codex_translation_uses_ephemeral_read_only_cli(self, _which):
        config = TranslationConfig(provider="codex", auth_root=self.auth_root, batch_size=2, retries=1)
        client = TranslationClient(config, runner=self._runner)
        translated, metadata = client.translate(["one", "two"], source_language="en", target_language="ko")
        command = next(command for command in self.commands if command[:2] == ["codex", "exec"])
        self.assertEqual(translated, ["번역 하나", "번역 둘"])
        self.assertEqual(metadata["provider"], "codex")
        self.assertIn("--ephemeral", command)
        self.assertIn("read-only", command)

    @patch("subtitle_automation.translation.shutil.which", return_value="/usr/local/bin/provider")
    def test_health_initializes_per_provider_auth_directories(self, _which):
        with tempfile.TemporaryDirectory() as temporary:
            auth_root = Path(temporary) / "auth"
            grok = TranslationClient(TranslationConfig(provider="grok", auth_root=auth_root), runner=self._runner)
            grok_status = grok.health()
            self.assertFalse(grok_status["available"])
            self.assertTrue((auth_root / "grok").is_dir())
            codex = TranslationClient(TranslationConfig(provider="codex", auth_root=auth_root), runner=self._runner)
            self.assertTrue(codex.health()["available"])
            self.assertTrue((auth_root / "codex").is_dir())

    def test_caption_format_is_limited_to_two_lines(self):
        source = "이 문장은 화면 한 줄에 길어서 두 줄로 자연스럽게 나뉘어야 합니다"
        formatted = _format_caption(source)
        self.assertLessEqual(len(formatted.splitlines()), 2)
        self.assertTrue(all(len(line) <= 23 for line in formatted.splitlines()))


if __name__ == "__main__":
    unittest.main()
