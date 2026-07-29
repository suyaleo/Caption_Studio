"""Caption translation through an OpenAI-compatible local oMLX server."""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable


DEFAULT_TRANSLATION_BASE_URL = "http://127.0.0.1:8000/v1"
LANGUAGE_NAMES = {
    "auto": "자동 감지 언어",
    "ko": "한국어",
    "en": "영어",
    "ja": "일본어",
    "zh": "중국어",
    "es": "스페인어",
    "fr": "프랑스어",
    "de": "독일어",
    "ru": "러시아어",
}


@dataclass(frozen=True)
class TranslationConfig:
    base_url: str = DEFAULT_TRANSLATION_BASE_URL
    api_key: str = "local"
    model: str | None = None
    timeout: float = 180.0
    health_timeout: float = 0.8
    batch_size: int = 10
    context_size: int = 10
    retries: int = 3

    @classmethod
    def from_env(cls) -> "TranslationConfig":
        return cls(
            base_url=os.getenv("CAPTION_TRANSLATION_BASE_URL", DEFAULT_TRANSLATION_BASE_URL),
            api_key=os.getenv("CAPTION_TRANSLATION_API_KEY", "local"),
            model=os.getenv("CAPTION_TRANSLATION_MODEL") or None,
            timeout=float(os.getenv("CAPTION_TRANSLATION_TIMEOUT", "180")),
            health_timeout=float(os.getenv("CAPTION_TRANSLATION_HEALTH_TIMEOUT", "0.8")),
            batch_size=max(1, int(os.getenv("CAPTION_TRANSLATION_BATCH_SIZE", "10"))),
            context_size=max(0, int(os.getenv("CAPTION_TRANSLATION_CONTEXT_SIZE", "10"))),
            retries=max(1, int(os.getenv("CAPTION_TRANSLATION_RETRIES", "3"))),
        )


class TranslationClient:
    def __init__(self, config: TranslationConfig | None = None) -> None:
        self.config = config or TranslationConfig.from_env()
        self.base_url = self.config.base_url.rstrip("/")

    def health(self) -> dict[str, Any]:
        try:
            payload = self._request("GET", "/models", timeout=self.config.health_timeout)
            models = _model_ids(payload)
            selected = self._select_model(models)
            return {
                "available": bool(selected),
                "base_url": self.base_url,
                "model": selected,
                "models": models,
                "error": None if selected else "oMLX에 로드된 모델이 없습니다.",
            }
        except Exception as exc:
            return {
                "available": False,
                "base_url": self.base_url,
                "model": self.config.model,
                "models": [],
                "error": _brief_error(exc),
            }

    def translate(
        self,
        texts: list[str],
        *,
        source_language: str,
        target_language: str,
        on_progress: Callable[[int, str], None] | None = None,
    ) -> tuple[list[str], dict[str, Any]]:
        if not texts:
            return [], {"provider": "local-oMLX", "model": None}
        models_payload = self._request("GET", "/models", timeout=self.config.health_timeout)
        model = self._select_model(_model_ids(models_payload))
        if not model:
            raise RuntimeError("oMLX에서 사용할 수 있는 번역 모델을 찾지 못했습니다.")

        translated: list[str] = []
        total_batches = (len(texts) + self.config.batch_size - 1) // self.config.batch_size
        for batch_index, start in enumerate(range(0, len(texts), self.config.batch_size), start=1):
            batch = texts[start : start + self.config.batch_size]
            context = translated[-self.config.context_size :] if self.config.context_size else []
            result = self._translate_batch_resilient(
                batch,
                context=context,
                source_language=source_language,
                target_language=target_language,
                model=model,
            )
            translated.extend(_format_caption(item) for item in result)
            if on_progress:
                on_progress(batch_index, f"자막 번역 중 · {batch_index}/{total_batches}")
        return translated, {
            "provider": "local-oMLX",
            "base_url": self.base_url,
            "model": model,
            "source_language": source_language,
            "target_language": target_language,
        }

    def _translate_batch_resilient(
        self,
        texts: list[str],
        *,
        context: list[str],
        source_language: str,
        target_language: str,
        model: str,
    ) -> list[str]:
        try:
            return self._translate_batch(
                texts,
                context=context,
                source_language=source_language,
                target_language=target_language,
                model=model,
            )
        except TranslationCountMismatch:
            if len(texts) <= 1:
                raise RuntimeError("로컬 번역 모델이 자막 한 항목을 누락했습니다.")
            midpoint = len(texts) // 2
            left = self._translate_batch_resilient(
                texts[:midpoint],
                context=context,
                source_language=source_language,
                target_language=target_language,
                model=model,
            )
            next_context = [*context, *left][-self.config.context_size :] if self.config.context_size else []
            right = self._translate_batch_resilient(
                texts[midpoint:],
                context=next_context,
                source_language=source_language,
                target_language=target_language,
                model=model,
            )
            return [*left, *right]

    def _translate_batch(
        self,
        texts: list[str],
        *,
        context: list[str],
        source_language: str,
        target_language: str,
        model: str,
    ) -> list[str]:
        source_name = LANGUAGE_NAMES.get(source_language, source_language)
        target_name = LANGUAGE_NAMES.get(target_language, target_language)
        system = (
            "당신은 영화와 SNS 영상 자막 전문 번역가입니다. 의미, 말투, 감정, 인물 관계를 보존하면서 "
            "직역투를 피하고 화면에서 즉시 읽히는 자연스러운 자막으로 번역하세요. "
            "입력 항목의 수와 순서를 반드시 유지하고 번역문 문자열만 담은 JSON 배열로 답하세요. "
            "설명, 마크다운, 번호는 금지합니다. 각 항목은 공백 포함 46자를 절대 넘기지 마세요. "
            "길면 핵심 의미와 말투를 보존해 간결하게 압축하고, 한 줄 23자 이내 또는 최대 두 줄로 작성하세요."
        )
        user_payload = {
            "source_language": source_name,
            "target_language": target_name,
            "previous_translated_context": context,
            "captions": texts,
            "constraints": {
                "max_characters_per_item_including_spaces": 46,
                "max_lines_per_item": 2,
                "preserve_item_count_and_order": True,
            },
        }
        last_error: Exception | None = None
        for attempt in range(self.config.retries):
            try:
                response = self._request(
                    "POST",
                    "/chat/completions",
                    {
                        "model": model,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
                        ],
                        "temperature": 0.2,
                        "max_tokens": max(512, len(texts) * 120),
                    },
                    timeout=self.config.timeout,
                )
                content = str(response["choices"][0]["message"]["content"])
                result = _json_string_array(content)
                if len(result) != len(texts):
                    if len(texts) == 1:
                        raise ValueError(f"단일 번역 항목 수가 다릅니다 ({len(result)}/1).")
                    raise TranslationCountMismatch(len(result), len(texts))
                non_empty = sum(bool(item.strip()) for item in result)
                if non_empty != len(texts):
                    if len(texts) > 1:
                        raise TranslationCountMismatch(non_empty, len(texts))
                    raise ValueError("번역 결과가 비어 있습니다.")
                result = [
                    item
                    if len(_clean_caption(item)) <= 46
                    else self._compress_caption(
                        item,
                        source_text=texts[index],
                        target_language=target_language,
                        model=model,
                    )
                    for index, item in enumerate(result)
                ]
                return result
            except TranslationCountMismatch:
                raise
            except (KeyError, IndexError, TypeError, ValueError, RuntimeError) as exc:
                last_error = exc
                if attempt + 1 < self.config.retries:
                    time.sleep(min(0.25 * (attempt + 1), 0.75))
        raise RuntimeError(f"로컬 번역 모델의 응답을 처리하지 못했습니다: {last_error}")

    def _compress_caption(
        self,
        translation: str,
        *,
        source_text: str,
        target_language: str,
        model: str,
    ) -> str:
        target_name = LANGUAGE_NAMES.get(target_language, target_language)
        payload = {
            "task": "shorten_video_caption",
            "target_language": target_name,
            "source_caption": source_text,
            "translation_to_shorten": _clean_caption(translation),
            "max_characters_including_spaces": 46,
        }
        last_error: Exception | None = None
        for attempt in range(self.config.retries):
            try:
                response = self._request(
                    "POST",
                    "/chat/completions",
                    {
                        "model": model,
                        "messages": [
                            {
                                "role": "system",
                                "content": (
                                    "당신은 영상 자막 편집자입니다. 원문의 핵심 의미와 말투를 유지하며 번역문을 "
                                    "공백 포함 46자 이하로 압축하세요. 내용을 임의로 생략하는 말줄임표는 금지합니다. "
                                    "압축한 번역문 하나만 담은 JSON 배열로 답하세요."
                                ),
                            },
                            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                        ],
                        "temperature": 0.1,
                        "max_tokens": 192,
                    },
                    timeout=self.config.timeout,
                )
                content = str(response["choices"][0]["message"]["content"])
                shortened = _json_string_array(content)
                if len(shortened) != 1:
                    raise ValueError("압축 번역은 한 항목이어야 합니다.")
                clean = _clean_caption(shortened[0])
                if not clean:
                    raise ValueError("압축 번역 결과가 비어 있습니다.")
                if len(clean) > 46:
                    raise ValueError(f"압축 번역 결과가 46자를 초과했습니다 ({len(clean)}자).")
                if "…" in clean or "..." in clean:
                    raise ValueError("압축 번역 결과에 말줄임표가 있습니다.")
                return clean
            except (KeyError, IndexError, TypeError, ValueError, RuntimeError) as exc:
                last_error = exc
                if attempt + 1 < self.config.retries:
                    time.sleep(min(0.25 * (attempt + 1), 0.75))
        raise RuntimeError(f"긴 자막을 안전하게 압축하지 못했습니다: {last_error}")

    def _select_model(self, models: list[str]) -> str | None:
        if self.config.model:
            return self.config.model if self.config.model in models else None
        return models[0] if models else None

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout: float,
    ) -> dict[str, Any]:
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            method=method,
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                parsed = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"oMLX HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"oMLX 서버({self.base_url})에 연결할 수 없습니다.") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError("oMLX가 올바른 JSON 객체를 반환하지 않았습니다.")
        return parsed


def translation_health(config: TranslationConfig | None = None) -> dict[str, Any]:
    return TranslationClient(config).health()


class TranslationCountMismatch(ValueError):
    def __init__(self, actual: int, expected: int) -> None:
        super().__init__(f"번역 항목 수가 다릅니다 ({actual}/{expected}).")


def translate_caption_texts(
    texts: list[str],
    *,
    source_language: str,
    target_language: str,
    config: TranslationConfig | None = None,
    on_progress: Callable[[int, str], None] | None = None,
) -> tuple[list[str], dict[str, Any]]:
    return TranslationClient(config).translate(
        texts,
        source_language=source_language,
        target_language=target_language,
        on_progress=on_progress,
    )


def _model_ids(payload: dict[str, Any]) -> list[str]:
    data = payload.get("data")
    if not isinstance(data, list):
        return []
    return [str(item["id"]) for item in data if isinstance(item, dict) and item.get("id")]


def _json_string_array(content: str) -> list[str]:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.IGNORECASE)
    candidates = [cleaned]
    start, end = cleaned.find("["), cleaned.rfind("]")
    if 0 <= start < end:
        candidates.insert(0, cleaned[start : end + 1])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            parsed = parsed.get("translations") or parsed.get("captions") or parsed.get("result")
        if isinstance(parsed, list) and all(isinstance(item, (str, int, float)) for item in parsed):
            return [str(item).strip() for item in parsed]
    raise ValueError("번역 응답에 JSON 문자열 배열이 없습니다.")


def _format_caption(value: str, *, max_chars: int = 23) -> str:
    clean = _clean_caption(value)
    if len(clean) <= max_chars:
        return clean
    candidates = [
        index
        for index in range(1, min(len(clean), max_chars + 1))
        if clean[index].isspace() and len(clean[index + 1 :].strip()) <= max_chars
    ]
    split_at = min(candidates, key=lambda index: abs(index - len(clean) / 2)) if candidates else max_chars
    first = clean[:split_at].strip()
    second = clean[split_at:].strip()
    return f"{first}\n{second}" if second else first


def _clean_caption(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\r", " ").replace("\n", " ")).strip().strip('"')


def _brief_error(error: Exception) -> str:
    value = str(error).strip()
    return value[:240] if value else error.__class__.__name__
