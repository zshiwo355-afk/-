from __future__ import annotations

import asyncio
from typing import Callable

from openai import OpenAI

from backend.config import AppConfig
from backend.translator.validator import (
    AUTH_FAILURE_MESSAGE,
    TranslationAuthError,
    TranslationResponse,
    TranslationTimeoutError,
)


class HyMT2Client:
    def __init__(self, config: AppConfig):
        self.config = config
        self.client = OpenAI(
            api_key=config.tokenhub_api_key,
            base_url=config.tokenhub_base_url,
            timeout=max(1, config.request_timeout_seconds),
        )

    @staticmethod
    def is_auth_error(exc: Exception) -> bool:
        message = str(exc).lower()
        status_code = getattr(exc, "status_code", None)
        code = getattr(exc, "code", None)
        return (
            status_code == 401
            or "401002" in message
            or "invalid api key" in message
            or ("ascii" in message and "codec can't encode" in message)
            or code == "401002"
        )

    def _validate_auth_config(self) -> None:
        api_key = self.config.tokenhub_api_key.strip()
        if not api_key or any(ord(char) > 127 for char in api_key):
            raise TranslationAuthError(AUTH_FAILURE_MESSAGE, raw_error="TOKENHUB_API_KEY is missing or non-ASCII")

    def _create_non_stream_completion(
        self,
        messages: list[dict[str, str]],
        on_first_response: Callable[[], None] | None = None,
    ) -> str:
        completion = self.client.chat.completions.create(
            model=self.config.model,
            messages=messages,
            temperature=self.config.temperature,
            stream=False,
            timeout=max(1, self.config.request_timeout_seconds),
        )
        if on_first_response:
            on_first_response()
        return completion.choices[0].message.content or ""

    def _create_stream_completion(
        self,
        messages: list[dict[str, str]],
        on_delta: Callable[[str], None] | None = None,
        on_first_response: Callable[[], None] | None = None,
    ) -> str:
        stream = self.client.chat.completions.create(
            model=self.config.model,
            messages=messages,
            temperature=self.config.temperature,
            stream=True,
            timeout=max(1, self.config.stream_timeout_seconds),
        )
        parts: list[str] = []
        saw_response = False
        for event in stream:
            if not event.choices:
                continue
            delta = event.choices[0].delta.content or ""
            if not saw_response:
                saw_response = True
                if on_first_response:
                    on_first_response()
            if delta:
                parts.append(delta)
                if on_delta:
                    on_delta(delta)
        text = "".join(parts)
        if not saw_response and on_first_response:
            on_first_response()
        if not text.strip():
            raise RuntimeError("Stream returned empty response")
        return text

    async def _run_with_timeout(self, func: Callable[[], str], timeout_seconds: int, label: str) -> str:
        try:
            return await asyncio.wait_for(asyncio.to_thread(func), timeout=max(1, timeout_seconds))
        except asyncio.TimeoutError as exc:
            raise TranslationTimeoutError(f"{label} timed out", timeout_seconds=timeout_seconds) from exc

    async def translate_chunk(
        self,
        messages: list[dict[str, str]],
        stream: bool,
        on_delta: Callable[[str], None] | None = None,
        on_first_response: Callable[[], None] | None = None,
        on_stream_fallback: Callable[[Exception], None] | None = None,
    ) -> TranslationResponse:
        self._validate_auth_config()
        if stream:
            try:
                text = await self._run_with_timeout(
                    lambda: self._create_stream_completion(messages, on_delta, on_first_response),
                    self.config.stream_timeout_seconds,
                    "stream request",
                )
                return TranslationResponse(text=text, used_stream=True)
            except Exception as exc:
                if self.is_auth_error(exc):
                    raise TranslationAuthError(AUTH_FAILURE_MESSAGE, raw_error=str(exc)) from exc
                if not self.config.stream_fallback:
                    raise
                if on_stream_fallback:
                    on_stream_fallback(exc)
                try:
                    fallback_text = await self._run_with_timeout(
                        lambda: self._create_non_stream_completion(messages, on_first_response),
                        self.config.request_timeout_seconds,
                        "non-stream fallback request",
                    )
                except Exception as fallback_exc:
                    if self.is_auth_error(fallback_exc):
                        raise TranslationAuthError(AUTH_FAILURE_MESSAGE, raw_error=str(fallback_exc)) from fallback_exc
                    raise fallback_exc from exc
                return TranslationResponse(
                    text=fallback_text,
                    used_stream=False,
                    stream_fallback_used=True,
                    raw_error=str(exc),
                )

        try:
            text = await self._run_with_timeout(
                lambda: self._create_non_stream_completion(messages, on_first_response),
                self.config.request_timeout_seconds,
                "non-stream request",
            )
        except Exception as exc:
            if self.is_auth_error(exc):
                raise TranslationAuthError(AUTH_FAILURE_MESSAGE, raw_error=str(exc)) from exc
            raise
        return TranslationResponse(text=text, used_stream=False)

    async def translate_single_segment(self, messages: list[dict[str, str]]) -> TranslationResponse:
        return await self.translate_chunk(messages=messages, stream=False)
