from __future__ import annotations

import asyncio
from typing import Callable

from openai import OpenAI

from backend.config import AppConfig
from backend.translator.validator import AUTH_FAILURE_MESSAGE, TranslationAuthError, TranslationResponse


class HyMT2Client:
    def __init__(self, config: AppConfig):
        self.config = config
        self.client = OpenAI(api_key=config.tokenhub_api_key, base_url=config.tokenhub_base_url)

    @staticmethod
    def is_auth_error(exc: Exception) -> bool:
        message = str(exc).lower()
        status_code = getattr(exc, "status_code", None)
        code = getattr(exc, "code", None)
        return status_code == 401 or "401002" in message or "invalid api key" in message or code == "401002"

    def _create_non_stream_completion(self, messages: list[dict[str, str]]) -> str:
        completion = self.client.chat.completions.create(
            model=self.config.model,
            messages=messages,
            temperature=self.config.temperature,
            stream=False,
        )
        return completion.choices[0].message.content or ""

    def _create_stream_completion(
        self,
        messages: list[dict[str, str]],
        on_delta: Callable[[str], None] | None = None,
    ) -> str:
        stream = self.client.chat.completions.create(
            model=self.config.model,
            messages=messages,
            temperature=self.config.temperature,
            stream=True,
        )
        parts: list[str] = []
        for event in stream:
            if not event.choices:
                continue
            delta = event.choices[0].delta.content or ""
            if delta:
                parts.append(delta)
                if on_delta:
                    on_delta(delta)
        return "".join(parts)

    async def translate_chunk(
        self,
        messages: list[dict[str, str]],
        stream: bool,
        on_delta: Callable[[str], None] | None = None,
    ) -> TranslationResponse:
        if stream:
            try:
                text = await asyncio.to_thread(self._create_stream_completion, messages, on_delta)
                return TranslationResponse(text=text, used_stream=True)
            except Exception as exc:
                if self.is_auth_error(exc):
                    raise TranslationAuthError(AUTH_FAILURE_MESSAGE, raw_error=str(exc)) from exc
                try:
                    fallback_text = await asyncio.to_thread(self._create_non_stream_completion, messages)
                except Exception as fallback_exc:
                    if self.is_auth_error(fallback_exc):
                        raise TranslationAuthError(AUTH_FAILURE_MESSAGE, raw_error=str(fallback_exc)) from fallback_exc
                    raise
                return TranslationResponse(
                    text=fallback_text,
                    used_stream=False,
                    stream_fallback_used=True,
                    raw_error=str(exc),
                )

        try:
            text = await asyncio.to_thread(self._create_non_stream_completion, messages)
        except Exception as exc:
            if self.is_auth_error(exc):
                raise TranslationAuthError(AUTH_FAILURE_MESSAGE, raw_error=str(exc)) from exc
            raise
        return TranslationResponse(text=text, used_stream=False)
