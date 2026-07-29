"""OpenAI-compatible local LLM client for oMLX and similar local servers."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


DEFAULT_BASE_URL = "http://127.0.0.1:8000/v1"
DEFAULT_API_KEY = "local"
DEFAULT_MODEL = "Ornith-1.0-35B-8bit"


@dataclass(frozen=True)
class LocalLLMConfig:
    base_url: str = DEFAULT_BASE_URL
    api_key: str = DEFAULT_API_KEY
    model: str = DEFAULT_MODEL
    timeout: float = 180.0

    @classmethod
    def from_env(cls) -> "LocalLLMConfig":
        return cls(
            base_url=os.environ.get("LOCAL_LLM_BASE_URL", DEFAULT_BASE_URL),
            api_key=os.environ.get("LOCAL_LLM_API_KEY", DEFAULT_API_KEY),
            model=os.environ.get("LOCAL_LLM_MODEL", DEFAULT_MODEL),
            timeout=float(os.environ.get("LOCAL_LLM_TIMEOUT", "180")),
        )


class LocalLLMClient:
    def __init__(self, config: LocalLLMConfig | None = None):
        self.config = config or LocalLLMConfig.from_env()
        self.base_url = self.config.base_url.rstrip("/")
        self.model = self.config.model

    def list_models(self) -> dict[str, Any]:
        return self._request("GET", "/models")

    def chat(self, messages: list[dict[str, str]], max_tokens: int) -> dict[str, Any]:
        payload = {
            "model": self.config.model,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        return self._request("POST", "/chat/completions", payload)

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
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
            with urllib.request.urlopen(request, timeout=self.config.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"local LLM HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"local LLM connection failed: {exc}") from exc


def extract_message_content(response: dict[str, Any]) -> str:
    try:
        return str(response["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("chat completion response does not contain choices[0].message.content") from exc


def extract_json_payload(content: str) -> dict[str, Any]:
    """Extract the first valid JSON object from a local model response."""

    candidates = _json_candidates(content)
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("local LLM response did not contain a valid JSON object")


def _json_candidates(content: str) -> list[str]:
    fenced = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", content, flags=re.DOTALL | re.IGNORECASE)
    candidates = list(fenced)
    start = content.find("{")
    while start != -1:
        candidate = _balanced_object_at(content, start)
        if candidate:
            candidates.append(candidate)
            break
        start = content.find("{", start + 1)
    candidates.append(content.strip())
    return candidates


def _balanced_object_at(text: str, start: int) -> str | None:
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None
