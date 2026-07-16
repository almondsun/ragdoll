"""Structured model-provider adapters."""

from __future__ import annotations

import json
import os
from collections import deque
from typing import Any, Protocol, TypeVar

import httpx
from openai import OpenAI
from pydantic import BaseModel

from .config import Settings

T = TypeVar("T", bound=BaseModel)


class ProviderError(RuntimeError):
    """A provider could not return valid structured output."""


class ModelProvider(Protocol):
    def structured(
        self, *, instructions: str, prompt: str, response_model: type[T], quality: bool = False
    ) -> T: ...


class OpenAIProvider:
    def __init__(self, settings: Settings, client: OpenAI | None = None) -> None:
        if client is None and not os.getenv("OPENAI_API_KEY"):
            raise ProviderError(
                "OPENAI_API_KEY is not set; use --provider ollama or configure a key"
            )
        self.settings = settings
        self.client = client or OpenAI()

    def structured(
        self, *, instructions: str, prompt: str, response_model: type[T], quality: bool = False
    ) -> T:
        model = self.settings.openai_model_quality if quality else self.settings.openai_model_fast
        try:
            response = self.client.responses.parse(
                model=model,
                instructions=instructions,
                input=prompt,
                text_format=response_model,
            )
        except Exception as error:  # SDK exceptions vary by transport and version.
            raise ProviderError(
                "OpenAI request failed; check the configured model, API access, and network"
            ) from error
        parsed = response.output_parsed
        if parsed is None:
            raise ProviderError("OpenAI returned no structured output")
        return parsed


class OllamaProvider:
    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        self.settings = settings
        self.client = client or httpx.Client(
            timeout=settings.ollama_timeout_seconds, trust_env=False
        )

    def structured(
        self, *, instructions: str, prompt: str, response_model: type[T], quality: bool = False
    ) -> T:
        del quality
        payload: dict[str, Any] = {
            "model": self.settings.ollama_model,
            "stream": False,
            "think": False,
            "format": response_model.model_json_schema(),
            "messages": [
                {"role": "system", "content": instructions},
                {"role": "user", "content": prompt},
            ],
            "options": {"temperature": 0, "num_ctx": 8192, "num_predict": 768},
        }
        last_error: Exception | None = None
        for _ in range(2):
            try:
                response = self.client.post(f"{self.settings.ollama_url}/api/chat", json=payload)
                response.raise_for_status()
                content = response.json()["message"]["content"]
                return response_model.model_validate_json(content)
            except (httpx.HTTPError, KeyError, json.JSONDecodeError, ValueError) as error:
                last_error = error
                payload["messages"].append(
                    {
                        "role": "user",
                        "content": (
                            "Return only valid JSON matching the supplied schema. "
                            "Repair the prior output."
                        ),
                    }
                )
        raise ProviderError(f"Ollama returned invalid structured output: {last_error}")


class FakeProvider:
    """Deterministic provider for contract and end-to-end tests."""

    def __init__(self, responses: list[BaseModel]) -> None:
        self.responses = deque(responses)

    def structured(
        self, *, instructions: str, prompt: str, response_model: type[T], quality: bool = False
    ) -> T:
        del instructions, prompt, quality
        if not self.responses:
            raise ProviderError("fake provider response queue is empty")
        return response_model.model_validate(self.responses.popleft().model_dump())


def make_provider(settings: Settings) -> ModelProvider:
    if settings.provider == "openai":
        return OpenAIProvider(settings)
    if settings.provider == "ollama":
        return OllamaProvider(settings)
    raise ProviderError(f"unsupported provider: {settings.provider}")
