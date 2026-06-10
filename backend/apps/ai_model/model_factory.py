from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class OpenAICompatibleClient:
    api_key: str
    base_url: str
    model: str
    timeout_seconds: int = 60

    def complete(self, prompt: str) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": "Return only valid JSON. You generate safe pandas analysis code for an uploaded CSV.",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
        }
        request = urllib.request.Request(
            self.base_url.rstrip("/") + "/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:  # noqa: S310
            body = json.loads(response.read().decode("utf-8"))
        return str(body["choices"][0]["message"]["content"])


def create_llm_client() -> OpenAICompatibleClient:
    _load_local_env()
    provider = _selected_provider()
    if provider == "deepseek":
        api_key = _required_env("DEEPSEEK_API_KEY")
        base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
        model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    elif provider == "openai":
        api_key = _required_env("OPENAI_API_KEY")
        base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    else:
        raise RuntimeError(f"Unsupported LLM provider: {provider}")
    timeout_seconds = int(os.getenv("VDS_LITE_LLM_TIMEOUT_SECONDS") or os.getenv("VDS_LLM_TIMEOUT_SECONDS") or "60")
    return OpenAICompatibleClient(api_key=api_key, base_url=base_url, model=model, timeout_seconds=timeout_seconds)


def _selected_provider() -> str:
    for name in ("VDS_LITE_LLM_PROVIDER", "VDS_LLM_PROVIDER"):
        provider = (os.getenv(name) or "").strip().lower()
        if provider and provider != "mock":
            return provider
    return "deepseek"


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _load_local_env() -> None:
    env_path = Path(__file__).resolve().parents[3] / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and not os.environ.get(key):
            os.environ[key] = value
