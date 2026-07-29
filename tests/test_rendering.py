import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from subtitle_automation.rendering import captions_to_ass, render_hardsub_video


class RenderingTests(unittest.TestCase):
    def test_ass_preserves_caption_style_and_korean_text(self):
        ass = captions_to_ass(
            [
                {
                    "id": "caption-1",
                    "start": 0,
                    "end": 2.4,
                    "text": "안녕하세요\nCaption Studio",
                    "styleOverride": {
                        "position": "top",
                        "align": "right",
                        "color": "#ff783d",
                        "fontFamily": "BM Jua",
                        "offsetX": -24,
                        "offsetY": 48,
                    },
                }
            ],
            {"fontSize": 52, "outlineEnabled": True, "backgroundEnabled": True},
        )

        self.assertIn("PlayResX: 1920", ass)
        self.assertIn("Style: Caption1", ass)
        self.assertIn("&H003D78FF", ass)
        self.assertIn(",9,48,48,48,1", ass)
        self.assertIn("Style: Caption1,BM Jua,", ass)
        self.assertIn(r"{\pos(1848,96)}", ass)
        self.assertIn(r"안녕하세요\NCaption Studio", ass)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg is required")
    def test_hardsub_renderer_writes_playable_mp4_and_ass_evidence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "source.mp4"
            output = root / "render output" / "captioned.mp4"
            subprocess.run(
                [
                    shutil.which("ffmpeg"),
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=0x203040:s=640x360:d=1.2:r=24",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    str(source),
                ],
                check=True,
                capture_output=True,
            )

            progress = []
            result = render_hardsub_video(
                source,
                [{"id": "one", "start": 0.05, "end": 1.0, "text": "렌더링 검증"}],
                {"fontSize": 36, "backgroundEnabled": True},
                output,
                on_progress=lambda value, message: progress.append((value, message)),
            )

            self.assertTrue(output.exists())
            self.assertGreater(output.stat().st_size, 1000)
            self.assertTrue(output.with_suffix(".ass").exists())
            self.assertEqual(result["video"]["codec_name"], "h264")
            self.assertGreaterEqual(result["duration_seconds"], 1.1)
            self.assertEqual(progress[-1][0], 100)


if __name__ == "__main__":
    unittest.main()
