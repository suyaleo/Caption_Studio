"""ASS subtitle generation and FFmpeg hard-sub rendering."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable


DEFAULT_RENDER_STYLE: dict[str, Any] = {
    "fontFamily": "Apple SD Gothic Neo",
    "fontSize": 48,
    "color": "#ffffff",
    "outlineEnabled": True,
    "outlineColor": "#000000",
    "outlineWidth": 2,
    "backgroundEnabled": True,
    "backgroundColor": "rgba(0,0,0,0.62)",
    "position": "bottom",
    "align": "center",
    "offsetX": 0,
    "offsetY": 0,
}


def captions_to_ass(
    captions: list[dict[str, Any]],
    global_style: dict[str, Any] | None = None,
    *,
    play_res_x: int = 1920,
    play_res_y: int = 1080,
    font_name: str = "Apple SD Gothic Neo",
) -> str:
    """Serialize browser caption segments to Advanced SubStation Alpha."""

    base_style = {**DEFAULT_RENDER_STYLE, **(global_style or {})}
    styles: list[str] = []
    events: list[str] = []

    for index, caption in enumerate(sorted(captions, key=lambda item: float(item["start"])), start=1):
        style = {**base_style, **(caption.get("styleOverride") or {})}
        style_name = f"Caption{index}"
        styles.append(_ass_style(style_name, style, font_name))
        events.append(
            "Dialogue: 0,{start},{end},{style},,0,0,0,,{text}".format(
                start=_ass_timestamp(float(caption["start"])),
                end=_ass_timestamp(float(caption["end"])),
                style=style_name,
                text=_position_override(style, play_res_x, play_res_y) + _ass_text(str(caption.get("text", ""))),
            )
        )

    header = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {max(1, int(play_res_x))}",
        f"PlayResY: {max(1, int(play_res_y))}",
        "ScaledBorderAndShadow: yes",
        "WrapStyle: 0",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        *styles,
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        *events,
    ]
    return "\n".join(header) + "\n"


def render_hardsub_video(
    media_path: Path,
    captions: list[dict[str, Any]],
    global_style: dict[str, Any] | None,
    output_path: Path,
    *,
    ass_path: Path | None = None,
    on_progress: Callable[[int, str], None] | None = None,
) -> dict[str, Any]:
    """Render captions into an MP4, preserving an ASS evidence file."""

    ffmpeg, ffprobe, supports_ass = resolve_ffmpeg_tools()
    if not ffmpeg or not ffprobe:
        raise RuntimeError("FFmpeg가 설치되어 있지 않습니다. macOS에서는 `brew install ffmpeg-full`을 실행하세요.")
    if not supports_ass:
        raise RuntimeError("설치된 FFmpeg에 libass 자막 필터가 없습니다. macOS에서는 `brew install ffmpeg-full`을 실행하세요.")
    if not captions:
        raise ValueError("렌더링할 자막이 없습니다.")

    probe = _probe(media_path, ffprobe)
    width, height = _video_size(probe)
    duration = _duration(probe)
    ass_output = ass_path or output_path.with_suffix(".ass")
    ass_output.parent.mkdir(parents=True, exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ass_output.write_text(
        captions_to_ass(captions, global_style, play_res_x=width, play_res_y=height),
        encoding="utf-8",
    )

    if on_progress:
        on_progress(8, "렌더링 준비")
    filter_value = f"ass=filename='{_escape_filter_path(ass_output.resolve())}'"
    command = [
        ffmpeg,
        "-y",
        "-i",
        str(media_path),
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-vf",
        filter_value,
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "18",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        "-progress",
        "pipe:1",
        "-nostats",
        str(output_path),
    ]
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    assert process.stdout is not None
    for line in process.stdout:
        key, _, value = line.strip().partition("=")
        if key in {"out_time_us", "out_time_ms"} and duration > 0 and value.isdigit() and on_progress:
            rendered_seconds = int(value) / 1_000_000
            on_progress(min(94, 10 + int((rendered_seconds / duration) * 84)), "자막을 영상에 입히는 중")
    stderr = process.stderr.read() if process.stderr else ""
    return_code = process.wait()
    process.stdout.close()
    if process.stderr:
        process.stderr.close()
    if return_code != 0:
        raise RuntimeError(f"FFmpeg 렌더링에 실패했습니다: {_tail(stderr)}")
    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError("FFmpeg가 출력 파일을 만들지 못했습니다.")

    output_probe = _probe(output_path, ffprobe)
    if on_progress:
        on_progress(100, "완성 영상 준비 완료")
    return {
        "output": str(output_path),
        "ass": str(ass_output),
        "size_bytes": output_path.stat().st_size,
        "duration_seconds": _duration(output_probe),
        "video": _first_stream(output_probe, "video"),
        "audio": _first_stream(output_probe, "audio"),
    }


@lru_cache(maxsize=1)
def resolve_ffmpeg_tools() -> tuple[str | None, str | None, bool]:
    """Prefer an FFmpeg build that contains the libass filters."""

    configured = os.getenv("CAPTION_STUDIO_FFMPEG")
    candidates = [
        configured,
        "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg",
        "/usr/local/opt/ffmpeg-full/bin/ffmpeg",
        shutil.which("ffmpeg"),
    ]
    fallback: tuple[str | None, str | None, bool] = (None, None, False)
    for raw_candidate in candidates:
        if not raw_candidate:
            continue
        candidate = str(Path(raw_candidate))
        if not Path(candidate).is_file():
            continue
        ffprobe = str(Path(candidate).with_name("ffprobe"))
        if not Path(ffprobe).is_file():
            ffprobe = shutil.which("ffprobe") or ""
        supports_ass = _supports_ass_filter(candidate)
        resolved = (candidate, ffprobe or None, supports_ass)
        if fallback[0] is None:
            fallback = resolved
        if supports_ass and ffprobe:
            return resolved
    return fallback


def _supports_ass_filter(ffmpeg: str) -> bool:
    completed = subprocess.run(
        [ffmpeg, "-hide_banner", "-filters"],
        text=True,
        capture_output=True,
        check=False,
    )
    return bool(re.search(r"\s(?:ass|subtitles)\s", completed.stdout))


def _ass_style(name: str, style: dict[str, Any], font_name: str) -> str:
    outline = max(0, int(style.get("outlineWidth", 2))) if style.get("outlineEnabled", True) else 0
    background_enabled = bool(style.get("backgroundEnabled", False))
    border_style = 3 if background_enabled else 1
    back_color = _ass_color(style.get("backgroundColor", "rgba(0,0,0,0.62)"))
    return (
        "Style: {name},{font},{size},{primary},&H000000FF,{outline_color},{back},-1,0,0,0,100,100,0,0,{border},{outline},0,{alignment},48,48,48,1"
    ).format(
        name=name,
        font=_ass_font_name(style.get("fontFamily") or font_name),
        size=max(8, int(style.get("fontSize", 48))),
        primary=_ass_color(style.get("color", "#ffffff")),
        outline_color=_ass_color(style.get("outlineColor", "#000000")),
        back=back_color,
        border=border_style,
        outline=outline,
        alignment=_alignment(style.get("position", "bottom"), style.get("align", "center")),
    )


def _ass_timestamp(seconds: float) -> str:
    centiseconds = max(0, int(round(seconds * 100)))
    hours, remainder = divmod(centiseconds, 360_000)
    minutes, remainder = divmod(remainder, 6_000)
    whole_seconds, fraction = divmod(remainder, 100)
    return f"{hours}:{minutes:02}:{whole_seconds:02}.{fraction:02}"


def _ass_text(text: str) -> str:
    return text.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}").replace("\r\n", r"\N").replace("\n", r"\N")


def _ass_color(value: Any) -> str:
    raw = str(value).strip()
    hex_match = re.fullmatch(r"#([0-9a-fA-F]{6})([0-9a-fA-F]{2})?", raw)
    if hex_match:
        rgb = hex_match.group(1)
        alpha = int(hex_match.group(2), 16) if hex_match.group(2) else 255
        red, green, blue = int(rgb[0:2], 16), int(rgb[2:4], 16), int(rgb[4:6], 16)
        return f"&H{255 - alpha:02X}{blue:02X}{green:02X}{red:02X}"
    rgba_match = re.fullmatch(
        r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)(?:\s*,\s*([\d.]+))?\s*\)",
        raw,
        flags=re.IGNORECASE,
    )
    if rgba_match:
        red, green, blue = (min(255, int(rgba_match.group(index))) for index in (1, 2, 3))
        opacity = min(1.0, max(0.0, float(rgba_match.group(4) or 1)))
        return f"&H{round((1 - opacity) * 255):02X}{blue:02X}{green:02X}{red:02X}"
    return "&H00FFFFFF"


def _alignment(position: Any, align: Any) -> int:
    row = {"bottom": 0, "middle": 3, "top": 6}.get(str(position), 0)
    column = {"left": 1, "center": 2, "right": 3}.get(str(align), 2)
    return row + column


def _ass_font_name(value: Any) -> str:
    clean = re.sub(r"[,\r\n]", " ", str(value)).strip()
    return clean or "Apple SD Gothic Neo"


def _position_override(style: dict[str, Any], width: int, height: int) -> str:
    try:
        offset_x = int(round(float(style.get("offsetX", 0))))
        offset_y = int(round(float(style.get("offsetY", 0))))
    except (TypeError, ValueError):
        offset_x = offset_y = 0
    if offset_x == 0 and offset_y == 0:
        return ""
    x = {"left": 48, "center": width // 2, "right": width - 48}.get(str(style.get("align")), width // 2)
    y = {"top": 48, "middle": height // 2, "bottom": height - 48}.get(str(style.get("position")), height - 48)
    return rf"{{\pos({x + offset_x},{y + offset_y})}}"


def _escape_filter_path(path: Path) -> str:
    return str(path).replace("\\", r"\\").replace(":", r"\:").replace("'", r"\'").replace(",", r"\,")


def _probe(path: Path, ffprobe: str) -> dict[str, Any]:
    completed = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration,size:stream=index,codec_type,codec_name,width,height,duration",
            "-of",
            "json",
            str(path),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {_tail(completed.stderr)}")
    return json.loads(completed.stdout)


def _video_size(probe: dict[str, Any]) -> tuple[int, int]:
    video = _first_stream(probe, "video") or {}
    return int(video.get("width") or 1920), int(video.get("height") or 1080)


def _duration(probe: dict[str, Any]) -> float:
    return round(float((probe.get("format") or {}).get("duration") or 0), 3)


def _first_stream(probe: dict[str, Any], kind: str) -> dict[str, Any] | None:
    return next((dict(stream) for stream in probe.get("streams", []) if stream.get("codec_type") == kind), None)


def _tail(value: str, limit: int = 1200) -> str:
    clean = value.strip()
    return clean[-limit:] if len(clean) > limit else clean
