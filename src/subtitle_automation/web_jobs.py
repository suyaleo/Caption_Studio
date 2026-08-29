"""Local job orchestration for the Caption Studio web app."""

from __future__ import annotations

import json
from dataclasses import replace
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .media_input import asr_provider_status, build_input_job_from_asr, extract_audio, normalize_asr_model, probe_media, transcribe_audio
from .rendering import render_hardsub_video, resolve_ffmpeg_tools
from .runner import run_complete_job
from .oauth import OAuthLoginManager
from .translation import TranslationConfig, translate_caption_texts, translation_health


class WebJobManager:
    """Own media uploads and bounded background jobs for one local user."""

    def __init__(self, root: Path, *, max_workers: int = 1) -> None:
        self.root = Path(root).resolve()
        self.media_root = self.root / "media"
        self.jobs_root = self.root / "jobs"
        self.media_root.mkdir(parents=True, exist_ok=True)
        self.jobs_root.mkdir(parents=True, exist_ok=True)
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="caption-studio")
        self.oauth = OAuthLoginManager()

    def health(self) -> dict[str, Any]:
        ffmpeg, ffprobe, supports_ass = resolve_ffmpeg_tools()
        translator = translation_health()
        asr = asr_provider_status()
        return {
            "ok": bool(ffmpeg and ffprobe and supports_ass and asr["available"]),
            "ffmpeg": ffmpeg,
            "ffprobe": ffprobe,
            "ffmpeg_ass": supports_ass,
            "asr": asr,
            "mlx_whisper": bool(asr["installed"]["mlx-whisper"]),
            "translator": translator,
            "workspace": str(self.root),
        }

    def oauth_status(self, provider: str) -> dict[str, Any]:
        return self.oauth.status(provider)

    def start_oauth_login(self, provider: str) -> dict[str, Any]:
        return self.oauth.start(provider)

    def create_media(self, filename: str, source_stream: Any, content_length: int) -> dict[str, Any]:
        safe_name = _safe_media_name(filename)
        media_id = uuid.uuid4().hex
        media_dir = self.media_root / media_id
        media_dir.mkdir(parents=True)
        media_path = media_dir / safe_name
        remaining = content_length
        with media_path.open("wb") as destination:
            while remaining > 0:
                chunk = source_stream.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise ValueError("영상 업로드가 중간에 종료되었습니다.")
                destination.write(chunk)
                remaining -= len(chunk)
        metadata = {
            "media_id": media_id,
            "filename": safe_name,
            "size_bytes": media_path.stat().st_size,
            "path": str(media_path),
            "created_at": _now(),
        }
        (media_dir / "media.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return {key: value for key, value in metadata.items() if key != "path"}

    def start_transcription(
        self,
        media_id: str,
        *,
        asr_model: str,
        source_language: str,
        translate: bool = False,
        target_language: str = "ko",
        translation_provider: str = "none",
    ) -> dict[str, Any]:
        media = self._media(media_id)
        job = self._create_job("transcribe", media_id)
        self._executor.submit(
            self._run_transcription,
            job["job_id"],
            media,
            asr_model,
            source_language,
            translate,
            target_language,
            translation_provider,
        )
        return job

    def start_render(
        self,
        media_id: str,
        *,
        captions: list[dict[str, Any]],
        global_style: dict[str, Any],
    ) -> dict[str, Any]:
        media = self._media(media_id)
        if not captions:
            raise ValueError("렌더링할 자막이 없습니다.")
        job = self._create_job("render", media_id)
        self._executor.submit(self._run_render, job["job_id"], media, captions, global_style)
        return job

    def get_job(self, job_id: str) -> dict[str, Any]:
        safe_id = _safe_id(job_id)
        with self._lock:
            job = self._jobs.get(safe_id)
            if job:
                return _public_job(job)
        job_path = self.jobs_root / safe_id / "job.json"
        if not job_path.exists():
            raise KeyError(job_id)
        return _public_job(json.loads(job_path.read_text(encoding="utf-8")))

    def download_path(self, job_id: str) -> tuple[Path, str]:
        job = self.get_job(job_id)
        if job.get("kind") != "render" or job.get("status") != "complete":
            raise ValueError("완료된 영상 출력 작업이 아닙니다.")
        output = self.jobs_root / _safe_id(job_id) / "captioned.mp4"
        if not output.exists():
            raise FileNotFoundError(output)
        return output, str(job.get("download_name") or "caption-studio-output.mp4")

    def _run_transcription(
        self,
        job_id: str,
        media: dict[str, Any],
        asr_model: str,
        source_language: str,
        translate: bool,
        target_language: str,
        translation_provider: str,
    ) -> None:
        asr_model = normalize_asr_model(asr_model)
        job_dir = self.jobs_root / job_id
        media_path = Path(media["path"])
        try:
            self._update(job_id, status="running", progress=5, phase="probe", message="영상 정보를 확인하는 중")
            prepared_dir = job_dir / "prepared"
            prepared_dir.mkdir(parents=True, exist_ok=True)
            probe = probe_media(media_path)
            (prepared_dir / "probe.json").write_text(json.dumps(probe, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            self._update(job_id, progress=14, phase="audio", message="음성을 추출하는 중")
            audio_path = extract_audio(media_path, prepared_dir / "source.wav")
            self._update(job_id, progress=28, phase="transcribe", message="음성을 듣고 자막을 만드는 중")
            asr_result = transcribe_audio(
                audio_path,
                asr_model,
                language=None if source_language == "auto" else source_language.lower().split("-", 1)[0],
            )
            (prepared_dir / "asr.json").write_text(json.dumps(asr_result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            self._update(job_id, progress=74, phase="segment", message="자막 구간을 다듬는 중")
            detected_language = str(asr_result.get("language") or source_language or "auto").lower().split("-", 1)[0]
            input_job = build_input_job_from_asr(
                media_path=media_path,
                asr_result=asr_result,
                media_probe=probe,
                job_id=job_id,
                asr_model=asr_model,
                source_language=detected_language,
                target_language=detected_language,
            )
            output_dir = job_dir / "result"
            qa_passed = True
            try:
                manifest = run_complete_job(input_job, output_dir, mode="local", fallback="local")
            except RuntimeError:
                manifest_path = output_dir / "reports" / "manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
                qa_passed = False
            cues_path = output_dir / "subtitles" / "cues.json"
            if not cues_path.exists():
                raise RuntimeError("자막 결과 파일이 생성되지 않았습니다.")
            cue_result = json.loads(cues_path.read_text(encoding="utf-8"))
            qa_path = output_dir / "reports" / "qa.json"
            qa = json.loads(qa_path.read_text(encoding="utf-8")) if qa_path.exists() else {"passed": qa_passed, "flags": []}
            captions = [
                {
                    "id": str(cue.get("cue_id") or f"cue-{index}"),
                    "start": int(cue["start_ms"]) / 1000,
                    "end": int(cue["end_ms"]) / 1000,
                    "text": "\n".join(str(line) for line in cue.get("lines", [])),
                    "confidence": cue.get("confidence"),
                    "flags": cue.get("flags", []),
                }
                for index, cue in enumerate(cue_result.get("subtitle_cues", []), start=1)
            ]
            translation: dict[str, Any] | None = None
            if translate and captions:
                self._update(job_id, progress=82, phase="translate", message=f"{translation_provider.title()}로 자막을 번역하는 중")
                source_texts = [str(caption["text"]) for caption in captions]
                translated_texts, translation = translate_caption_texts(
                    source_texts,
                    source_language=detected_language,
                    target_language=target_language,
                    config=replace(TranslationConfig.from_env(), provider=translation_provider),
                    on_progress=lambda _batch, message: self._update(
                        job_id,
                        progress=88,
                        phase="translate",
                        message=message,
                    ),
                )
                for caption, source_text, translated_text in zip(captions, source_texts, translated_texts, strict=True):
                    caption["sourceText"] = source_text
                    caption["sourceLanguage"] = detected_language
                    caption["targetLanguage"] = target_language
                    caption["text"] = translated_text
                    caption["flags"] = [*caption.get("flags", []), f"translated_{translation_provider}"]
            self._update(
                job_id,
                status="complete",
                progress=100,
                phase="complete",
                message=(
                    "번역 자막 생성 완료"
                    if translate and qa.get("passed")
                    else "번역 자막 생성 완료 · 검토가 필요한 구간이 있습니다"
                    if translate
                    else "자동 자막 생성 완료"
                    if qa.get("passed")
                    else "자막 생성 완료 · 검토가 필요한 구간이 있습니다"
                ),
                result={
                    "captions": captions,
                    "qa": qa,
                    "manifest": manifest,
                    "asr_model": asr_model,
                    "source_language": detected_language,
                    "translation": translation,
                },
            )
        except Exception as exc:
            self._fail(job_id, exc)

    def _run_render(
        self,
        job_id: str,
        media: dict[str, Any],
        captions: list[dict[str, Any]],
        global_style: dict[str, Any],
    ) -> None:
        job_dir = self.jobs_root / job_id
        try:
            self._update(job_id, status="running", progress=4, phase="prepare", message="출력 설정을 준비하는 중")
            output_path = job_dir / "captioned.mp4"
            result = render_hardsub_video(
                Path(media["path"]),
                captions,
                global_style,
                output_path,
                ass_path=job_dir / "captions.ass",
                on_progress=lambda progress, message: self._update(
                    job_id,
                    progress=progress,
                    phase="render",
                    message=message,
                ),
            )
            download_name = f"{Path(media['filename']).stem}-captioned.mp4"
            public_result = {key: value for key, value in result.items() if key not in {"output", "ass"}}
            self._update(
                job_id,
                status="complete",
                progress=100,
                phase="complete",
                message="완성 영상을 다운로드할 수 있습니다",
                result=public_result,
                download_name=download_name,
                download_url=f"/api/jobs/{job_id}/download",
            )
        except Exception as exc:
            self._fail(job_id, exc)

    def _create_job(self, kind: str, media_id: str) -> dict[str, Any]:
        job_id = uuid.uuid4().hex
        job = {
            "job_id": job_id,
            "kind": kind,
            "media_id": media_id,
            "status": "queued",
            "progress": 0,
            "phase": "queued",
            "message": "작업 대기 중",
            "created_at": _now(),
            "updated_at": _now(),
        }
        (self.jobs_root / job_id).mkdir(parents=True)
        with self._lock:
            self._jobs[job_id] = job
            self._persist(job)
        return _public_job(job)

    def _update(self, job_id: str, **patch: Any) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.update(patch)
            job["updated_at"] = _now()
            self._persist(job)

    def _fail(self, job_id: str, error: Exception) -> None:
        self._update(
            job_id,
            status="error",
            phase="error",
            message="작업을 완료하지 못했습니다",
            error=str(error),
        )

    def _persist(self, job: dict[str, Any]) -> None:
        path = self.jobs_root / job["job_id"] / "job.json"
        path.write_text(json.dumps(job, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _media(self, media_id: str) -> dict[str, Any]:
        safe_id = _safe_id(media_id)
        metadata_path = self.media_root / safe_id / "media.json"
        if not metadata_path.exists():
            raise KeyError(media_id)
        return json.loads(metadata_path.read_text(encoding="utf-8"))


def _safe_id(value: str) -> str:
    if len(value) != 32 or any(character not in "0123456789abcdef" for character in value):
        raise KeyError(value)
    return value


def _safe_media_name(value: str) -> str:
    name = Path(value).name.strip() or "source.mp4"
    if Path(name).suffix.lower() not in {".mp4", ".mov", ".m4v", ".webm", ".mkv"}:
        raise ValueError("MP4, MOV, M4V, WebM 또는 MKV 영상만 사용할 수 있습니다.")
    return name


def _public_job(job: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in job.items() if key not in {"internal_path"}}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
