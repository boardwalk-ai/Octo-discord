"""Thin async client for the OpenRouter chat-completions API.

The model is passed in per-request so it can be switched live from the bot
(see the /model command) without any code change.
"""
from __future__ import annotations

import httpx

import config


class OpenRouterError(RuntimeError):
    pass


class OpenRouterClient:
    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=config.OPENROUTER_BASE_URL,
            headers={
                "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
                "HTTP-Referer": config.OPENROUTER_APP_URL,
                "X-Title": config.OPENROUTER_APP_NAME,
            },
            timeout=60.0,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str,
        *,
        max_tokens: int = 800,
        temperature: float = 0.7,
    ) -> str:
        """Send a chat completion, falling back to the configured model on error."""
        models_to_try = [model]
        if config.OPENROUTER_FALLBACK_MODEL and config.OPENROUTER_FALLBACK_MODEL != model:
            models_to_try.append(config.OPENROUTER_FALLBACK_MODEL)

        last_error: Exception | None = None
        for candidate in models_to_try:
            try:
                return await self._request(candidate, messages, max_tokens, temperature)
            except Exception as exc:  # noqa: BLE001 - try the next model
                last_error = exc
        raise OpenRouterError(str(last_error) if last_error else "Unknown error")

    async def _request(
        self,
        model: str,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float,
    ) -> str:
        resp = await self._client.post(
            "/chat/completions",
            json={
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        try:
            return data["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError) as exc:
            raise OpenRouterError(f"Unexpected response shape: {data}") from exc
