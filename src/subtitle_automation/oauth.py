"""Device-login process management for isolated CLI OAuth credentials."""

from __future__ import annotations

import subprocess
import threading
from dataclasses import dataclass, field
from typing import Any

from .translation import SUPPORTED_PROVIDERS, TranslationConfig, provider_environment, translation_health


@dataclass
class DeviceLogin:
    provider: str
    process: subprocess.Popen[str]
    lines: list[str] = field(default_factory=list)
    finished: bool = False
    returncode: int | None = None


class OAuthLoginManager:
    def __init__(self, config: TranslationConfig | None = None) -> None:
        self.config = config or TranslationConfig.from_env()
        self._logins: dict[str, DeviceLogin] = {}
        self._lock = threading.Lock()

    def status(self, provider: str) -> dict[str, Any]:
        _validate(provider)
        with self._lock:
            login = self._logins.get(provider)
            snapshot = _snapshot(login) if login else None
        health = translation_health(_provider_config(self.config, provider))
        return {**health, "login": snapshot}

    def start(self, provider: str) -> dict[str, Any]:
        _validate(provider)
        with self._lock:
            current = self._logins.get(provider)
            if current and current.process.poll() is None:
                return _snapshot(current)
            command = ["grok", "login", "--device-auth"] if provider == "grok" else ["codex", "login", "--device-auth"]
            process = subprocess.Popen(
                command,
                env=provider_environment(provider, self.config.auth_root),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            login = DeviceLogin(provider=provider, process=process)
            self._logins[provider] = login
            thread = threading.Thread(target=self._collect, args=(login,), daemon=True, name=f"caption-{provider}-oauth")
            thread.start()
            return _snapshot(login)

    def _collect(self, login: DeviceLogin) -> None:
        assert login.process.stdout is not None
        for line in login.process.stdout:
            with self._lock:
                login.lines.append(line.strip())
                del login.lines[:-24]
        with self._lock:
            login.returncode = login.process.wait()
            login.finished = True


def _provider_config(config: TranslationConfig, provider: str) -> TranslationConfig:
    return TranslationConfig(
        provider=provider,
        model=config.model,
        timeout=config.timeout,
        health_timeout=config.health_timeout,
        batch_size=config.batch_size,
        context_size=config.context_size,
        retries=config.retries,
        auth_root=config.auth_root,
    )


def _validate(provider: str) -> None:
    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError("지원하지 않는 OAuth 공급자입니다.")


def _snapshot(login: DeviceLogin) -> dict[str, Any]:
    state = "completed" if login.finished and login.returncode == 0 else "failed" if login.finished else "waiting"
    return {"provider": login.provider, "state": state, "instructions": "\n".join(line for line in login.lines if line)[-4000:]}
