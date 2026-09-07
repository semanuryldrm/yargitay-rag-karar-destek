"""Environment-backed settings for the local Yargitay RAG API."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from scripts.lmstudio_embeddings import DEFAULT_BASE_URL, DEFAULT_EMBEDDING_MODEL
from scripts.lmstudio_chat import DEFAULT_CHAT_MODEL
from scripts.qdrant_vector_store import DEFAULT_COLLECTION_NAME, DEFAULT_VECTOR_SIZE


DEFAULT_DATABASE_PATH = Path("data/vector_store/qdrant")
DEFAULT_EXPECTED_POINT_COUNT = 31_544


class SettingsError(RuntimeError):
    """Raised when an API setting is invalid or unsafe to use."""


def _positive_integer(value: str, *, name: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise SettingsError(f"{name} must be an integer") from exc
    if parsed < 1:
        raise SettingsError(f"{name} must be positive")
    return parsed


@dataclass(frozen=True)
class Settings:
    lmstudio_base_url: str = DEFAULT_BASE_URL
    embedding_model: str = DEFAULT_EMBEDDING_MODEL
    chat_model: str = DEFAULT_CHAT_MODEL
    qdrant_path: Path = DEFAULT_DATABASE_PATH
    qdrant_collection: str = DEFAULT_COLLECTION_NAME
    vector_size: int = DEFAULT_VECTOR_SIZE
    expected_point_count: int = DEFAULT_EXPECTED_POINT_COUNT

    @classmethod
    def from_environment(cls) -> "Settings":
        """Build settings from optional YARGITAY_RAG_* environment variables."""
        return cls(
            lmstudio_base_url=os.getenv(
                "YARGITAY_RAG_LMSTUDIO_URL", DEFAULT_BASE_URL
            ).strip(),
            embedding_model=os.getenv(
                "YARGITAY_RAG_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL
            ).strip(),
            chat_model=os.getenv(
                "YARGITAY_RAG_CHAT_MODEL", DEFAULT_CHAT_MODEL
            ).strip(),
            qdrant_path=Path(
                os.getenv("YARGITAY_RAG_QDRANT_PATH", str(DEFAULT_DATABASE_PATH))
            ),
            qdrant_collection=os.getenv(
                "YARGITAY_RAG_QDRANT_COLLECTION", DEFAULT_COLLECTION_NAME
            ).strip(),
            vector_size=_positive_integer(
                os.getenv("YARGITAY_RAG_VECTOR_SIZE", str(DEFAULT_VECTOR_SIZE)),
                name="YARGITAY_RAG_VECTOR_SIZE",
            ),
            expected_point_count=_positive_integer(
                os.getenv(
                    "YARGITAY_RAG_EXPECTED_POINTS",
                    str(DEFAULT_EXPECTED_POINT_COUNT),
                ),
                name="YARGITAY_RAG_EXPECTED_POINTS",
            ),
        )

    def validate(self) -> "Settings":
        if not self.lmstudio_base_url:
            raise SettingsError("LM Studio base URL is empty")
        if not self.embedding_model:
            raise SettingsError("Embedding model is empty")
        if not self.chat_model:
            raise SettingsError("Chat model is empty")
        if not self.qdrant_collection:
            raise SettingsError("Qdrant collection name is empty")
        if self.vector_size < 1:
            raise SettingsError("Vector size must be positive")
        if self.expected_point_count < 1:
            raise SettingsError("Expected point count must be positive")
        return self
