"""Bounded Groq calls; callers must invoke without an open database transaction."""

from typing import Any

import httpx

from app.core.config import Settings

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


class GroqError(Exception):
    def __init__(self, status: int = 503) -> None:
        self.status = status
        super().__init__("Groq is unavailable.")


def complete(settings: Settings, prompt: str, *, json_mode: bool = False) -> dict[str, str]:
    key = settings.groq_api_key
    if key is None or not key.get_secret_value().strip():
        raise GroqError()
    try:
        with httpx.Client(timeout=settings.groq_timeout_seconds, trust_env=False) as client:
            upstream = client.post(
                GROQ_URL,
                headers={"Authorization": f"Bearer {key.get_secret_value()}"},
                json={
                    "model": settings.groq_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_completion_tokens": 2048 if json_mode else 1024,
                    **({"response_format": {"type": "json_object"}} if json_mode else {}),
                },
            )
        if upstream.status_code == 429:
            raise GroqError(429)
        if upstream.status_code != 200:
            raise GroqError()
        payload: Any = upstream.json()
        content: Any = payload["choices"][0]["message"]["content"]
        if not isinstance(content, str) or not content.strip() or len(content) > 100000:
            raise ValueError("Invalid provider response")
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
        raise GroqError() from None
    return {"model": settings.groq_model, "content": content}
