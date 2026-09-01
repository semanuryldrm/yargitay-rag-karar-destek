"""Validated LM Studio embedding client and vector similarity helpers."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = "http://127.0.0.1:1234"
DEFAULT_EMBEDDING_MODEL = "text-embedding-embeddinggemma-300m"
DEFAULT_TIMEOUT_SECONDS = 60.0


class EmbeddingClientError(RuntimeError):
    """Raised when an embedding request or response is unsafe to use."""


def _validate_base_url(base_url: str) -> str:
    if not isinstance(base_url, str) or not base_url.strip():
        raise EmbeddingClientError("LM Studio base URL is empty")
    normalized = base_url.rstrip("/")
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise EmbeddingClientError(f"Invalid LM Studio base URL: {base_url!r}")
    return normalized


def _validate_texts(texts: Sequence[str]) -> list[str]:
    if isinstance(texts, (str, bytes)):
        raise EmbeddingClientError("Embedding input must be a sequence of texts")
    normalized = list(texts)
    if not normalized:
        raise EmbeddingClientError("At least one embedding input is required")
    for index, text in enumerate(normalized):
        if not isinstance(text, str) or not text.strip():
            raise EmbeddingClientError(
                f"Embedding input at index {index} is empty or not text"
            )
    return normalized


def _validated_vector(raw_vector: Any, *, item_index: int) -> list[float]:
    if not isinstance(raw_vector, list) or not raw_vector:
        raise EmbeddingClientError(
            f"Embedding at index {item_index} is empty or not an array"
        )
    vector: list[float] = []
    for coordinate_index, coordinate in enumerate(raw_vector):
        if isinstance(coordinate, bool) or not isinstance(coordinate, (int, float)):
            raise EmbeddingClientError(
                f"Embedding coordinate {coordinate_index} at index {item_index} "
                "is not numeric"
            )
        number = float(coordinate)
        if not math.isfinite(number):
            raise EmbeddingClientError(
                f"Embedding coordinate {coordinate_index} at index {item_index} "
                "is not finite"
            )
        vector.append(number)
    if math.sqrt(sum(value * value for value in vector)) == 0.0:
        raise EmbeddingClientError(f"Embedding at index {item_index} has zero norm")
    return vector


class LMStudioEmbeddingClient:
    """Small OpenAI-compatible client with strict local response validation."""

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_EMBEDDING_MODEL,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.base_url = _validate_base_url(base_url)
        if not isinstance(model, str) or not model.strip():
            raise EmbeddingClientError("Embedding model id is empty")
        if timeout_seconds <= 0:
            raise EmbeddingClientError("timeout_seconds must be positive")
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
            raise EmbeddingClientError(
                f"LM Studio returned HTTP {exc.code}{suffix}"
            ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise EmbeddingClientError(
                f"Could not reach LM Studio at {self.base_url}: {exc}"
            ) from exc

        try:
            decoded = raw_body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise EmbeddingClientError("LM Studio response is not valid UTF-8") from exc
        try:
            parsed = json.loads(decoded)
        except json.JSONDecodeError as exc:
            raise EmbeddingClientError("LM Studio response is not valid JSON") from exc
        if not isinstance(parsed, dict):
            raise EmbeddingClientError("LM Studio response is not a JSON object")
        if parsed.get("error"):
            raise EmbeddingClientError(f"LM Studio API error: {parsed['error']}")
        return parsed

    def list_models(self) -> tuple[str, ...]:
        response = self._request_json("GET", "/v1/models")
        data = response.get("data")
        if not isinstance(data, list):
            raise EmbeddingClientError("Model list response has no data array")
        model_ids: list[str] = []
        for index, item in enumerate(data):
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                raise EmbeddingClientError(
                    f"Invalid model list item at index {index}"
                )
            model_ids.append(item["id"])
        if len(model_ids) != len(set(model_ids)):
            raise EmbeddingClientError("Model list contains duplicate ids")
        return tuple(model_ids)

    def ensure_model_available(self) -> tuple[str, ...]:
        model_ids = self.list_models()
        if self.model not in model_ids:
            raise EmbeddingClientError(
                f"Embedding model is not available in LM Studio: {self.model}"
            )
        return model_ids

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        normalized_texts = _validate_texts(texts)
        response = self._request_json(
            "POST",
            "/v1/embeddings",
            {"model": self.model, "input": normalized_texts},
        )
        response_model = response.get("model")
        if response_model is not None and response_model != self.model:
            raise EmbeddingClientError(
                f"Embedding response model mismatch: {response_model!r}"
            )
        data = response.get("data")
        if not isinstance(data, list) or len(data) != len(normalized_texts):
            raise EmbeddingClientError(
                "Embedding response count does not match the input count"
            )

        indexed_vectors: dict[int, list[float]] = {}
        dimension: int | None = None
        for item_position, item in enumerate(data):
            if not isinstance(item, dict):
                raise EmbeddingClientError(
                    f"Embedding response item {item_position} is not an object"
                )
            item_index = item.get("index")
            if isinstance(item_index, bool) or not isinstance(item_index, int):
                raise EmbeddingClientError(
                    f"Embedding response item {item_position} has invalid index"
                )
            if not 0 <= item_index < len(normalized_texts):
                raise EmbeddingClientError(
                    f"Embedding response index is out of range: {item_index}"
                )
            if item_index in indexed_vectors:
                raise EmbeddingClientError(
                    f"Embedding response contains duplicate index: {item_index}"
                )
            vector = _validated_vector(item.get("embedding"), item_index=item_index)
            if dimension is None:
                dimension = len(vector)
            elif len(vector) != dimension:
                raise EmbeddingClientError(
                    "Embedding response contains inconsistent vector dimensions"
                )
            indexed_vectors[item_index] = vector

        expected_indexes = set(range(len(normalized_texts)))
        if set(indexed_vectors) != expected_indexes:
            raise EmbeddingClientError("Embedding response indexes are incomplete")
        return [indexed_vectors[index] for index in range(len(normalized_texts))]

    def embed_text(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]


def vector_norm(vector: Sequence[float]) -> float:
    if not vector:
        raise EmbeddingClientError("Vector is empty")
    squared_sum = 0.0
    for index, coordinate in enumerate(vector):
        if isinstance(coordinate, bool) or not isinstance(coordinate, (int, float)):
            raise EmbeddingClientError(f"Vector coordinate {index} is not numeric")
        number = float(coordinate)
        if not math.isfinite(number):
            raise EmbeddingClientError(f"Vector coordinate {index} is not finite")
        squared_sum += number * number
    norm = math.sqrt(squared_sum)
    if norm == 0.0:
        raise EmbeddingClientError("Vector has zero norm")
    return norm


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise EmbeddingClientError(
            f"Vector dimension mismatch: {len(left)} != {len(right)}"
        )
    left_norm = vector_norm(left)
    right_norm = vector_norm(right)
    dot_product = sum(float(a) * float(b) for a, b in zip(left, right))
    similarity = dot_product / (left_norm * right_norm)
    if not math.isfinite(similarity):
        raise EmbeddingClientError("Cosine similarity is not finite")
    return max(-1.0, min(1.0, similarity))


def rank_by_similarity(
    query_vector: Sequence[float],
    candidate_vectors: Mapping[str, Sequence[float]],
) -> list[tuple[str, float]]:
    if not candidate_vectors:
        raise EmbeddingClientError("At least one candidate vector is required")
    ranked = [
        (candidate_id, cosine_similarity(query_vector, vector))
        for candidate_id, vector in candidate_vectors.items()
    ]
    return sorted(ranked, key=lambda item: (-item[1], item[0]))
