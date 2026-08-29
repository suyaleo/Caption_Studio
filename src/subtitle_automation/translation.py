"""Caption translation through isolated Grok or Codex CLI OAuth sessions."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

LANGUAGE_NAMES = {
    "auto": "자동 감지 언어", "ko": "한국어", "en": "영어", "ja": "일본어",
    "zh": "중국어", "es": "스페인어", "fr": "프랑스어", "de": "독일어", "ru": "러시아어",
}
SUPPORTED_PROVIDERS = {"grok": "Grok", "codex": "Codex"}


@dataclass(frozen=True)
class TranslationConfig:
    provider: str = "none"
    model: str | None = None
    timeout: float = 180.0
    health_timeout: float = 8.0
    batch_size: int = 10
    context_size: int = 10
    retries: int = 3
    auth_root: Path = Path("/data/auth")

    @classmethod
    def from_env(cls) -> "TranslationConfig":
        return cls(
            provider=os.getenv("CAPTION_TRANSLATION_PROVIDER", "none").strip().lower(),
            model=os.getenv("CAPTION_TRANSLATION_MODEL") or None,
            timeout=float(os.getenv("CAPTION_TRANSLATION_TIMEOUT", "180")),
            health_timeout=float(os.getenv("CAPTION_TRANSLATION_HEALTH_TIMEOUT", "8")),
            batch_size=max(1, int(os.getenv("CAPTION_TRANSLATION_BATCH_SIZE", "10"))),
            context_size=max(0, int(os.getenv("CAPTION_TRANSLATION_CONTEXT_SIZE", "10"))),
            retries=max(1, int(os.getenv("CAPTION_TRANSLATION_RETRIES", "3"))),
            auth_root=Path(os.getenv("CAPTION_TRANSLATION_AUTH_ROOT", "/data/auth")),
        )


def provider_environment(provider: str, auth_root: Path) -> dict[str, str]:
    environment = dict(os.environ)
    credential_root = auth_root / provider
    if provider in SUPPORTED_PROVIDERS:
        credential_root.mkdir(parents=True, exist_ok=True)
    if provider == "grok":
        environment["HOME"] = str(credential_root)
    elif provider == "codex":
        environment["CODEX_HOME"] = str(credential_root)
    return environment


class TranslationClient:
    def __init__(
        self,
        config: TranslationConfig | None = None,
        *,
        runner: Callable[[list[str], dict[str, str], float], subprocess.CompletedProcess[str]] | None = None,
    ) -> None:
        self.config = config or TranslationConfig.from_env()
        self._runner = runner or _run_command

    def health(self) -> dict[str, Any]:
        provider = self.config.provider
        if provider == "none":
            return _health(provider, False, "번역 공급자를 선택하세요.", self.config.model)
        if provider not in SUPPORTED_PROVIDERS:
            return _health(provider, False, "지원하지 않는 번역 공급자입니다.", self.config.model)
        binary = "grok" if provider == "grok" else "codex"
        if not shutil.which(binary):
            return _health(provider, False, f"{binary} CLI가 컨테이너에 없습니다.", self.config.model)
        try:
            result = self._runner(
                ["grok", "models"] if provider == "grok" else ["codex", "login", "status"],
                provider_environment(provider, self.config.auth_root),
                self.config.health_timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return _health(provider, False, _brief_error(exc), self.config.model)
        error = _brief_error(result.stderr or result.stdout or "OAuth 로그인이 필요합니다.") if result.returncode else None
        return _health(provider, not result.returncode, error, self.config.model)

    def translate(
        self,
        texts: list[str],
        *,
        source_language: str,
        target_language: str,
        on_progress: Callable[[int, str], None] | None = None,
    ) -> tuple[list[str], dict[str, Any]]:
        if not texts:
            return [], _metadata(self.config, source_language, target_language)
        status = self.health()
        if not status["available"]:
            raise RuntimeError(str(status["error"]))
        translated: list[str] = []
        total = (len(texts) + self.config.batch_size - 1) // self.config.batch_size
        for batch_number, start in enumerate(range(0, len(texts), self.config.batch_size), start=1):
            batch = texts[start : start + self.config.batch_size]
            context = translated[-self.config.context_size :] if self.config.context_size else []
            result = self._translate_batch(batch, context, source_language, target_language)
            translated.extend(_format_caption(item) for item in result)
            if on_progress:
                on_progress(batch_number, f"{SUPPORTED_PROVIDERS[self.config.provider]}로 자막 번역 중 · {batch_number}/{total}")
        return translated, _metadata(self.config, source_language, target_language)

    def _translate_batch(self, texts: list[str], context: list[str], source_language: str, target_language: str) -> list[str]:
        prompt = (
            "You are a professional video-caption translator. Preserve meaning, tone, emotion, and item count/order. "
            "Return only a JSON array of translated strings; no markdown, explanations, or tool use. Each item must be "
            "at most 46 characters including spaces and use at most two subtitle lines.\n\n"
            + json.dumps({
                "source_language": LANGUAGE_NAMES.get(source_language, source_language),
                "target_language": LANGUAGE_NAMES.get(target_language, target_language),
                "previous_translated_context": context,
                "captions": texts,
            }, ensure_ascii=False)
        )
        last_error: Exception | None = None
        for attempt in range(self.config.retries):
            try:
                result = _json_string_array(self._invoke(prompt))
                if len(result) != len(texts) or any(not item.strip() for item in result):
                    raise RuntimeError(f"번역 항목 수가 다릅니다 ({len(result)}/{len(texts)}).")
                return result
            except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
                last_error = exc
                if attempt + 1 < self.config.retries:
                    time.sleep(min(0.25 * (attempt + 1), 0.75))
        raise RuntimeError(f"번역 응답을 처리하지 못했습니다: {last_error}")

    def _invoke(self, prompt: str) -> str:
        environment = provider_environment(self.config.provider, self.config.auth_root)
        if self.config.provider == "grok":
            command = ["grok", "--no-auto-update", "--no-plan", "--no-subagents", "--disable-web-search", "--output-format", "json", "-p", prompt]
            if self.config.model:
                command[1:1] = ["--model", self.config.model]
            result = self._runner(command, environment, self.config.timeout)
            if result.returncode:
                raise RuntimeError(_brief_error(result.stderr or result.stdout))
            return result.stdout
        with tempfile.NamedTemporaryFile(prefix="caption-codex-", suffix=".txt", delete=False) as handle:
            output = Path(handle.name)
        try:
            command = ["codex", "exec", "--ephemeral", "--skip-git-repo-check", "--ignore-rules", "--sandbox", "read-only", "--output-last-message", str(output), prompt]
            if self.config.model:
                command[2:2] = ["--model", self.config.model]
            result = self._runner(command, environment, self.config.timeout)
            if result.returncode:
                raise RuntimeError(_brief_error(result.stderr or result.stdout))
            return output.read_text(encoding="utf-8") if output.exists() else result.stdout
        finally:
            output.unlink(missing_ok=True)


def translation_health(config: TranslationConfig | None = None) -> dict[str, Any]:
    return TranslationClient(config).health()


def translate_caption_texts(
    texts: list[str],
    *,
    source_language: str,
    target_language: str,
    config: TranslationConfig | None = None,
    on_progress: Callable[[int, str], None] | None = None,
) -> tuple[list[str], dict[str, Any]]:
    return TranslationClient(config).translate(texts, source_language=source_language, target_language=target_language, on_progress=on_progress)


def _run_command(command: list[str], environment: dict[str, str], timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, env=environment, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False)


def _health(provider: str, available: bool, error: str | None, model: str | None) -> dict[str, Any]:
    return {"available": available, "provider": provider, "model": model or "subscription-default", "error": error}


def _metadata(config: TranslationConfig, source_language: str, target_language: str) -> dict[str, Any]:
    return {"provider": config.provider, "model": config.model or "subscription-default", "source_language": source_language, "target_language": target_language}


def _json_string_array(content: str) -> list[str]:
    marker = chr(96) * 3
    cleaned = re.sub(r"^" + marker + r"(?:json)?\s*|\s*" + marker + r"$", "", content.strip(), flags=re.IGNORECASE)
    options = [cleaned]
    start, end = cleaned.find("["), cleaned.rfind("]")
    if 0 <= start < end:
        options.insert(0, cleaned[start : end + 1])
    for candidate in options:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        found = _find_string_array(parsed)
        if found is not None:
            return found
    raise ValueError("번역 응답에 JSON 문자열 배열이 없습니다.")


def _find_string_array(value: Any) -> list[str] | None:
    if isinstance(value, list) and all(isinstance(item, (str, int, float)) for item in value):
        return [str(item).strip() for item in value]
    if isinstance(value, dict):
        for key in ("translations", "captions", "result", "content", "text", "message"):
            if key in value:
                found = _find_string_array(value[key])
                if found is not None:
                    return found
        for item in value.values():
            found = _find_string_array(item)
            if found is not None:
                return found
    if isinstance(value, str) and value.strip().startswith(("[", "{")):
        try:
            return _find_string_array(json.loads(value.strip()))
        except json.JSONDecodeError:
            return None
    if isinstance(value, list):
        for item in value:
            found = _find_string_array(item)
            if found is not None:
                return found
    return None


def _format_caption(value: str, *, max_chars: int = 23) -> str:
    clean = re.sub(r"\s+", " ", value.replace("\r", " ").replace("\n", " ")).strip().strip('"')
    if len(clean) <= max_chars:
        return clean
    split = max_chars
    spaces = [index for index in range(1, max_chars + 1) if clean[index].isspace() and len(clean[index + 1 :].strip()) <= max_chars]
    if spaces:
        split = min(spaces, key=lambda index: abs(index - len(clean) / 2))
    return f"{clean[:split].strip()}\n{clean[split:].strip()}"


def _brief_error(error: Exception | str) -> str:
    value = str(error).strip()
    return value[:240] if value else error.__class__.__name__ if isinstance(error, Exception) else "알 수 없는 오류"
