"""Validated LM Studio client for grounded Gemma chat generations."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = "http://127.0.0.1:1234"
DEFAULT_CHAT_MODEL = "google/gemma-4-12b-qat"
DEFAULT_TIMEOUT_SECONDS = 180.0
DEFAULT_MAX_OUTPUT_TOKENS = 700


class ChatClientError(RuntimeError):
    """Raised when an LM Studio chat request or response is unsafe to use."""


@dataclass(frozen=True)
class ChatGeneration:
    """One validated, non-reasoning LM Studio generation."""

    text: str
    model: str
    response_id: str | None
    stats: dict[str, int | float]


def _validate_base_url(base_url: str) -> str:
    if not isinstance(base_url, str) or not base_url.strip():
        raise ChatClientError("LM Studio base URL is empty")
    normalized = base_url.rstrip("/")
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ChatClientError(f"Invalid LM Studio base URL: {base_url!r}")
    return normalized


def _validate_prompt(value: str, *, name: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ChatClientError(f"{name} is empty or not text")
    normalized = value.strip()
    if len(normalized) > maximum:
        raise ChatClientError(f"{name} exceeds {maximum} characters")
    if "\x00" in normalized or "\ufffd" in normalized:
        raise ChatClientError(f"{name} contains invalid characters")
    return normalized


def _validate_stats(raw_stats: Any) -> dict[str, int | float]:
    if not isinstance(raw_stats, dict):
        raise ChatClientError("Chat response has no stats object")
    integer_fields = (
        "input_tokens",
        "total_output_tokens",
        "reasoning_output_tokens",
    )
    stats: dict[str, int | float] = {}
    for field in integer_fields:
        value = raw_stats.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ChatClientError(f"Chat response has invalid {field}")
        stats[field] = value
    if stats["reasoning_output_tokens"] != 0:
        raise ChatClientError("Reasoning output must be disabled for RAG answers")

    for field in (
        "tokens_per_second",
        "time_to_first_token_seconds",
        "model_load_time_seconds",
    ):
        value = raw_stats.get(field)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ChatClientError(f"Chat response has invalid {field}")
        number = float(value)
        if not math.isfinite(number) or number < 0:
            raise ChatClientError(f"Chat response has invalid {field}")
        stats[field] = number
    return stats


class LMStudioChatClient:
    """Small client for LM Studio's native non-streaming chat endpoint."""

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_CHAT_MODEL,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.base_url = _validate_base_url(base_url)
        if not isinstance(model, str) or not model.strip():
            raise ChatClientError("Chat model id is empty")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(float(timeout_seconds))
            or timeout_seconds <= 0
        ):
            raise ChatClientError("timeout_seconds must be a positive number")
        self.model = model.strip()
        self.timeout_seconds = float(timeout_seconds)

    def _request_json(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        body = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        request = Request(
            f"{self.base_url}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw_body = response.read()
        except HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8", errors="replace")[:500]
            except Exception:
                detail = ""
            suffix = f": {detail}" if detail else ""
            raise ChatClientError(
                f"LM Studio returned HTTP {exc.code}{suffix}"
            ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise ChatClientError(
                f"Could not reach LM Studio at {self.base_url}: {exc}"
            ) from exc

        try:
            decoded = raw_body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ChatClientError("LM Studio response is not valid UTF-8") from exc
        try:
            parsed = json.loads(decoded)
        except json.JSONDecodeError as exc:
            raise ChatClientError("LM Studio response is not valid JSON") from exc
        if not isinstance(parsed, dict):
            raise ChatClientError("LM Studio response is not a JSON object")
        if parsed.get("error"):
            raise ChatClientError(f"LM Studio API error: {parsed['error']}")
        return parsed

    def list_models(self) -> tuple[str, ...]:
        response = self._request_json("GET", "/v1/models")
        data = response.get("data")
        if not isinstance(data, list):
            raise ChatClientError("Model list response has no data array")
        model_ids: list[str] = []
        for index, item in enumerate(data):
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                raise ChatClientError(
                    f"Invalid model list item at index {index}"
                )
            model_ids.append(item["id"])
        if len(model_ids) != len(set(model_ids)):
            raise ChatClientError("Model list contains duplicate ids")
        return tuple(model_ids)

    def ensure_model_available(self) -> tuple[str, ...]:
        model_ids = self.list_models()
        if self.model not in model_ids:
            raise ChatClientError(
                f"Chat model is not available in LM Studio: {self.model}"
            )
        return model_ids

    def generate(
        self,
        *,
        system_prompt: str,
        input_text: str,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    ) -> ChatGeneration:
        validated_system = _validate_prompt(
            system_prompt, name="System prompt", maximum=20_000
        )
        validated_input = _validate_prompt(
            input_text, name="Chat input", maximum=60_000
        )
        if (
            isinstance(max_output_tokens, bool)
            or not isinstance(max_output_tokens, int)
            or not 64 <= max_output_tokens <= 2_000
        ):
            raise ChatClientError("max_output_tokens must be between 64 and 2000")

        response = self._request_json(
            "POST",
            "/api/v1/chat",
            {
                "model": self.model,
                "input": validated_input,
                "system_prompt": validated_system,
                "temperature": 0,
                "max_output_tokens": max_output_tokens,
                "reasoning": "off",
                "stream": False,
            },
        )
        response_model = response.get("model_instance_id")
        if response_model != self.model:
            raise ChatClientError(
                "Chat response model mismatch: "
                f"expected {self.model!r}, got {response_model!r}"
            )
        output = response.get("output")
        if not isinstance(output, list) or not output:
            raise ChatClientError("Chat response has no output array")
        if len(output) != 1 or not isinstance(output[0], dict):
            raise ChatClientError("Chat response must contain exactly one message")
        if output[0].get("type") != "message":
            raise ChatClientError("Chat response output is not a message")
        content = output[0].get("content")
        if not isinstance(content, str) or not content.strip():
            raise ChatClientError("Chat response message is empty")
        text = content.strip()
        if len(text) > 20_000 or "\x00" in text or "\ufffd" in text:
            raise ChatClientError("Chat response message is invalid")

        response_id = response.get("response_id")
        if response_id is not None and (
            not isinstance(response_id, str) or not response_id.strip()
        ):
            raise ChatClientError("Chat response has invalid response_id")
        return ChatGeneration(
            text=text,
            model=response_model,
            response_id=response_id,
            stats=_validate_stats(response.get("stats")),
        )
