"""Dependency-free local HTTP server for Caption Studio."""

from __future__ import annotations

import argparse
import json
import math
import mimetypes
import os
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import __version__
from .web_jobs import WebJobManager


DEFAULT_MAX_UPLOAD_BYTES = 4 * 1024 * 1024 * 1024
DEFAULT_MAX_JSON_BYTES = 8 * 1024 * 1024


class CaptionStudioServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        manager: WebJobManager,
        *,
        static_dir: Path | None = None,
    ) -> None:
        super().__init__(server_address, CaptionStudioHandler)
        self.manager = manager
        self.static_dir = static_dir.resolve() if static_dir else None
        self.max_upload_bytes = int(os.getenv("CAPTION_STUDIO_MAX_UPLOAD_BYTES", DEFAULT_MAX_UPLOAD_BYTES))


class CaptionStudioHandler(BaseHTTPRequestHandler):
    server: CaptionStudioServer

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.NO_CONTENT)
        self._cors_headers()
        self.end_headers()

    def do_HEAD(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self.send_response(HTTPStatus.OK)
            self._cors_headers()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return
        if self.server.static_dir:
            self._static(parsed.path, send_body=False)
            return
        self.send_response(HTTPStatus.NOT_FOUND)
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/health":
                self._json(HTTPStatus.OK, {**self.server.manager.health(), "version": __version__})
                return
            if parsed.path == "/api/version":
                self._json(
                    HTTPStatus.OK,
                    {
                        "displayName": "Caption Studio",
                        "repository": "Caption_Studio",
                        "slug": "caption-studio",
                        "version": __version__,
                        "license": "Apache-2.0",
                    },
                )
                return
            parts = [unquote(part) for part in parsed.path.split("/") if part]
            if len(parts) == 4 and parts[:2] == ["api", "auth"] and parts[3] == "status":
                self._json(HTTPStatus.OK, self.server.manager.oauth_status(parts[2]))
                return
            if len(parts) == 3 and parts[:2] == ["api", "jobs"]:
                self._json(HTTPStatus.OK, self.server.manager.get_job(parts[2]))
                return
            if len(parts) == 4 and parts[:2] == ["api", "jobs"] and parts[3] == "download":
                path, filename = self.server.manager.download_path(parts[2])
                self._file(path, filename, "video/mp4")
                return
            if self.server.static_dir:
                self._static(parsed.path)
                return
            self._json(HTTPStatus.NOT_FOUND, {"error": "요청한 경로가 없습니다."})
        except KeyError:
            self._json(HTTPStatus.NOT_FOUND, {"error": "작업 또는 미디어를 찾을 수 없습니다."})
        except (ValueError, FileNotFoundError) as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except Exception as exc:  # pragma: no cover - defensive server boundary.
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            parts = [unquote(part) for part in parsed.path.split("/") if part]
            if len(parts) == 5 and parts[:2] == ["api", "auth"] and parts[3:] == ["device", "start"]:
                self._json(HTTPStatus.ACCEPTED, self.server.manager.start_oauth_login(parts[2]))
                return
            if parsed.path == "/api/media":
                query = parse_qs(parsed.query)
                filename = (query.get("filename") or [""])[0]
                length = self._content_length(self.server.max_upload_bytes)
                result = self.server.manager.create_media(filename, self.rfile, length)
                self._json(HTTPStatus.CREATED, result)
                return
            if parsed.path == "/api/jobs/transcribe":
                payload = self._json_body()
                job = self.server.manager.start_transcription(
                    str(payload.get("media_id", "")),
                    asr_model=str(payload.get("asr_model") or "mlx-community/whisper-small-mlx"),
                    source_language=_language_code(payload.get("source_language"), default="auto"),
                    translate=bool(payload.get("translate", False)),
                    target_language=_language_code(payload.get("target_language"), default="ko"),
                    translation_provider=str(payload.get("translation_provider") or "none").lower(),
                )
                self._json(HTTPStatus.ACCEPTED, job)
                return
            if parsed.path == "/api/jobs/render":
                payload = self._json_body()
                captions = payload.get("captions")
                global_style = payload.get("global_style")
                if not isinstance(captions, list) or not isinstance(global_style, dict):
                    raise ValueError("자막 목록과 프로젝트 스타일이 필요합니다.")
                job = self.server.manager.start_render(
                    str(payload.get("media_id", "")),
                    captions=captions,
                    global_style=global_style,
                )
                self._json(HTTPStatus.ACCEPTED, job)
                return
            self._json(HTTPStatus.NOT_FOUND, {"error": "요청한 API가 없습니다."})
        except KeyError:
            self._json(HTTPStatus.NOT_FOUND, {"error": "업로드된 영상을 찾을 수 없습니다."})
        except ValueError as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except Exception as exc:  # pragma: no cover - defensive server boundary.
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})

    def _json_body(self) -> dict:
        length = self._content_length(DEFAULT_MAX_JSON_BYTES)
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("올바른 JSON 요청이 아닙니다.") from exc
        if not isinstance(payload, dict):
            raise ValueError("JSON 객체가 필요합니다.")
        return payload

    def _content_length(self, maximum: int) -> int:
        raw = self.headers.get("Content-Length")
        if not raw or not raw.isdigit():
            raise ValueError("Content-Length가 필요합니다.")
        length = int(raw)
        if length <= 0:
            raise ValueError("빈 요청은 처리할 수 없습니다.")
        if length > maximum:
            raise ValueError(f"요청 크기가 제한({maximum} bytes)을 넘었습니다.")
        return length

    def _json(self, status: HTTPStatus, payload: dict) -> None:
        body = json.dumps(_json_safe(payload), ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self._cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path: Path, filename: str, content_type: str) -> None:
        self.send_response(HTTPStatus.OK)
        self._cors_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(path.stat().st_size))
        self.send_header("Content-Disposition", f'attachment; filename="{_ascii_filename(filename)}"')
        self.end_headers()
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                self.wfile.write(chunk)

    def _static(self, raw_path: str, *, send_body: bool = True) -> None:
        assert self.server.static_dir is not None
        relative = unquote(raw_path).lstrip("/") or "index.html"
        candidate = (self.server.static_dir / relative).resolve()
        if self.server.static_dir not in candidate.parents and candidate != self.server.static_dir:
            self._json(HTTPStatus.FORBIDDEN, {"error": "허용되지 않은 경로입니다."})
            return
        if not candidate.is_file():
            candidate = self.server.static_dir / "index.html"
        if not candidate.is_file():
            self._json(HTTPStatus.NOT_FOUND, {"error": "웹 빌드 결과가 없습니다. 먼저 npm run build를 실행하세요."})
            return
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        body = candidate.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache" if candidate.name == "index.html" else "public, max-age=31536000, immutable")
        self.end_headers()
        if send_body:
            self.wfile.write(body)

    def _cors_headers(self) -> None:
        origin = self.headers.get("Origin")
        if origin in {"http://127.0.0.1:8788", "http://localhost:8788"}:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def log_message(self, format: str, *args: object) -> None:
        print(f"[caption-studio] {self.address_string()} {format % args}", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="caption-studio")
    parser.add_argument("--version", action="version", version=f"Caption Studio {__version__}")
    parser.add_argument("--host", default=os.getenv("CAPTION_STUDIO_HOST", "127.0.0.1"))
    parser.add_argument("--port", default=int(os.getenv("CAPTION_STUDIO_PORT", "8788")), type=int)
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--static-dir", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    workspace = args.workspace or Path(os.getenv("CAPTION_STUDIO_WORKSPACE", _default_workspace()))
    static_dir = args.static_dir or (
        Path(value) if (value := os.getenv("CAPTION_STUDIO_STATIC_DIR")) else _bundled_static_dir()
    )
    manager = WebJobManager(workspace)
    server = CaptionStudioServer((args.host, args.port), manager, static_dir=static_dir)
    print(f"Caption Studio API: http://{args.host}:{server.server_port}")
    if static_dir:
        print(f"Caption Studio web: http://{args.host}:{server.server_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def _bundled_static_dir() -> Path | None:
    directory = Path(__file__).with_name("static")
    return directory if (directory / "index.html").is_file() else None


def _default_workspace() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Caption Studio"
    if os.name == "nt" and (app_data := os.getenv("APPDATA")):
        return Path(app_data) / "Caption Studio"
    data_home = Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return data_home / "caption-studio"


def _ascii_filename(value: str) -> str:
    safe = "".join(character if character.isascii() and (character.isalnum() or character in ".-_") else "-" for character in value)
    return safe or "caption-studio-output.mp4"


def _json_safe(value: object) -> object:
    """Replace non-standard non-finite floats before sending browser JSON."""

    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    return value


def _language_code(value: object, *, default: str) -> str:
    code = str(value or default).strip().lower().split("-", 1)[0]
    if code not in {"auto", "ko", "en", "ja", "zh", "es", "fr", "de", "ru"}:
        raise ValueError("지원하지 않는 언어입니다.")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
