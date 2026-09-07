"""Validated semantic search over the indexed Yargitay decision chunks."""

from __future__ import annotations

import math
import re
import time
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from scripts.lmstudio_embeddings import EmbeddingClientError
from scripts.qdrant_vector_store import SearchHit, VectorStoreError


MIN_QUERY_CHARACTERS = 10
MAX_QUERY_CHARACTERS = 4_000
DEFAULT_TOP_K = 5
MAX_TOP_K = 20
SEARCH_EXPANSION_FACTOR = 5
MAX_SEARCH_CANDIDATES = 100
ALLOWED_DECISION_TYPES = frozenset({"hukuk", "ceza", "kurul"})
ALLOWED_QUALITY_STATES = frozenset({"gecerli", "uyarili"})
LEGAL_NOTICE = (
    "Sonuçlar yalnızca anlamsal benzerliğe göre sıralanmıştır; hukuki danışmanlık "
    "veya kesin hukuki görüş değildir."
)


class SemanticSearchError(RuntimeError):
    """Raised when a semantic search request cannot be completed safely."""


class QueryValidationError(SemanticSearchError):
    """Raised when a direct service caller supplies an invalid query."""


class EmbeddingClientProtocol(Protocol):
    model: str
    base_url: str

    def ensure_model_available(self) -> tuple[str, ...]: ...

    def embed_text(self, text: str) -> list[float]: ...


class VectorStoreProtocol(Protocol):
    collection_name: str

    def search(
        self,
        query_vector: Sequence[float],
        *,
        limit: int = 5,
        metadata_filters: Mapping[str, str | bool] | None = None,
        score_threshold: float | None = None,
    ) -> tuple[SearchHit, ...]: ...

    def count(self) -> int: ...


def normalize_query(value: str) -> str:
    """Normalize harmless whitespace without changing the query's meaning."""
    if not isinstance(value, str):
        raise QueryValidationError("Olay açıklaması metin olmalıdır")
    normalized = unicodedata.normalize("NFC", value).replace("\u00a0", " ")
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if len(normalized) < MIN_QUERY_CHARACTERS:
        raise QueryValidationError(
            f"Olay açıklaması en az {MIN_QUERY_CHARACTERS} karakter olmalıdır"
        )
    if len(normalized) > MAX_QUERY_CHARACTERS:
        raise QueryValidationError(
            f"Olay açıklaması en fazla {MAX_QUERY_CHARACTERS} karakter olabilir"
        )
    if "\x00" in normalized or "\ufffd" in normalized:
        raise QueryValidationError("Olay açıklaması geçersiz karakter içeriyor")
    return normalized


def validate_top_k(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise QueryValidationError("top_k tam sayı olmalıdır")
    if not 1 <= value <= MAX_TOP_K:
        raise QueryValidationError(f"top_k 1 ile {MAX_TOP_K} arasında olmalıdır")
    return value


def validate_min_score(value: float | None) -> float | None:
    """Validate an optional cosine-similarity lower bound."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise QueryValidationError("min_score sayısal veya null olmalıdır")
    threshold = float(value)
    if not math.isfinite(threshold) or not -1.0 <= threshold <= 1.0:
        raise QueryValidationError("min_score -1 ile 1 arasında olmalıdır")
    return threshold


def normalize_metadata_filters(
    value: Mapping[str, Any] | None,
) -> dict[str, str | bool]:
    """Normalize the public allow-listed exact-match search filters."""
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise QueryValidationError("filtreler bir nesne olmalıdır")

    allowed_fields = {
        "karar_turu",
        "daire",
        "veri_kalite_durumu",
        "metin_2000_karakter_sinirinda",
    }
    unknown_fields = set(value) - allowed_fields
    if unknown_fields:
        unknown = ", ".join(sorted(str(field) for field in unknown_fields))
        raise QueryValidationError(f"Desteklenmeyen metadata filtresi: {unknown}")

    normalized: dict[str, str | bool] = {}
    for field, raw_value in value.items():
        if raw_value is None:
            continue
        if field == "metin_2000_karakter_sinirinda":
            if not isinstance(raw_value, bool):
                raise QueryValidationError(f"{field} filtresi boolean olmalıdır")
            normalized[field] = raw_value
            continue
        if not isinstance(raw_value, str):
            raise QueryValidationError(f"{field} filtresi metin olmalıdır")
        text = re.sub(r"\s+", " ", raw_value).strip()
        if not text:
            raise QueryValidationError(f"{field} filtresi boş olamaz")
        if field == "karar_turu" and text not in ALLOWED_DECISION_TYPES:
            raise QueryValidationError("karar_turu hukuk, ceza veya kurul olmalıdır")
        if field == "veri_kalite_durumu" and text not in ALLOWED_QUALITY_STATES:
            raise QueryValidationError(
                "veri_kalite_durumu gecerli veya uyarili olmalıdır"
            )
        if field == "daire" and len(text) > 120:
            raise QueryValidationError("daire filtresi en fazla 120 karakter olabilir")
        normalized[field] = text
    return normalized


def _result_from_hit(hit: SearchHit, *, rank: int) -> dict[str, Any]:
    payload: Mapping[str, Any] = hit.payload
    required_text_fields = (
        "chunk_id",
        "karar_id",
        "daire",
        "karar_turu",
        "baslik",
        "chunk_metni",
        "kaynak",
        "kaynak_url",
        "kaynak_lisans",
    )
    for field in required_text_fields:
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            raise SemanticSearchError(
                f"Qdrant sonucu zorunlu {field!r} alanını içermiyor"
            )
    optional_text_fields = ("esas_no", "karar_no", "karar_tarihi")
    for field in optional_text_fields:
        value = payload.get(field)
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise SemanticSearchError(
                f"Qdrant sonucu geçersiz {field!r} alanı içeriyor"
            )
    chunk_index = payload.get("chunk_sirasi")
    chunk_count = payload.get("toplam_chunk")
    for field, value in (
        ("chunk_sirasi", chunk_index),
        ("toplam_chunk", chunk_count),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise SemanticSearchError(
                f"Qdrant sonucu geçersiz {field!r} alanı içeriyor"
            )
    if chunk_index > chunk_count:
        raise SemanticSearchError(
            "Qdrant sonucunda chunk_sirasi toplam_chunk değerini aşıyor"
        )
    warnings = payload.get("veri_kalite_uyarilari")
    if not isinstance(warnings, list) or not all(
        isinstance(item, str) and item.strip() for item in warnings
    ):
        raise SemanticSearchError("Qdrant sonucu geçersiz veri kalitesi uyarıları içeriyor")

    return {
        "sira": rank,
        "benzerlik_skoru": round(hit.score, 6),
        "chunk_id": payload["chunk_id"],
        "karar_id": payload["karar_id"],
        "chunk_sirasi": chunk_index,
        "toplam_chunk": chunk_count,
        "daire": payload["daire"],
        "karar_turu": payload["karar_turu"],
        "esas_no": payload.get("esas_no"),
        "karar_no": payload.get("karar_no"),
        "karar_tarihi": payload.get("karar_tarihi"),
        "baslik": payload["baslik"],
        "chunk_metni": payload["chunk_metni"],
        "veri_kalite_uyarilari": list(warnings),
        "kaynak": payload["kaynak"],
        "kaynak_url": payload["kaynak_url"],
        "kaynak_lisans": payload["kaynak_lisans"],
    }


def _unique_decision_hits(
    hits: Sequence[SearchHit], *, limit: int
) -> tuple[SearchHit, ...]:
    """Keep the highest-scoring chunk for each decision in ranked order."""
    selected: list[SearchHit] = []
    seen_decisions: set[str] = set()
    for hit in hits:
        decision_id = hit.payload.get("karar_id")
        if not isinstance(decision_id, str) or not decision_id.strip():
            raise SemanticSearchError("Qdrant sonucu geçerli karar_id içermiyor")
        if decision_id in seen_decisions:
            continue
        selected.append(hit)
        seen_decisions.add(decision_id)
        if len(selected) == limit:
            break
    return tuple(selected)


class SemanticSearchService:
    """Embed one legal-event query and retrieve nearest Yargitay chunks."""

    def __init__(
        self,
        *,
        embedding_client: EmbeddingClientProtocol,
        vector_store: VectorStoreProtocol,
        expected_point_count: int,
    ) -> None:
        if expected_point_count < 1:
            raise SemanticSearchError("Expected point count must be positive")
        self.embedding_client = embedding_client
        self.vector_store = vector_store
        self.expected_point_count = expected_point_count

    def health(self) -> dict[str, Any]:
        try:
            self.embedding_client.ensure_model_available()
            point_count = self.vector_store.count()
        except (EmbeddingClientError, VectorStoreError) as exc:
            raise SemanticSearchError(str(exc)) from exc
        if point_count != self.expected_point_count:
            raise SemanticSearchError(
                "Qdrant point count mismatch: "
                f"expected {self.expected_point_count}, got {point_count}"
            )
        return {
            "status": "ok",
            "embedding_model": self.embedding_client.model,
            "qdrant_collection": self.vector_store.collection_name,
            "indexed_chunks": point_count,
        }

    def search(
        self,
        query: str,
        *,
        top_k: int = DEFAULT_TOP_K,
        min_score: float | None = None,
        metadata_filters: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_query = normalize_query(query)
        validated_top_k = validate_top_k(top_k)
        validated_min_score = validate_min_score(min_score)
        validated_filters = normalize_metadata_filters(metadata_filters)
        candidate_limit = min(
            validated_top_k * SEARCH_EXPANSION_FACTOR,
            MAX_SEARCH_CANDIDATES,
        )
        started = time.perf_counter()
        try:
            query_vector = self.embedding_client.embed_text(normalized_query)
            hits = self.vector_store.search(
                query_vector,
                limit=candidate_limit,
                metadata_filters=validated_filters or None,
                score_threshold=validated_min_score,
            )
        except (EmbeddingClientError, VectorStoreError) as exc:
            raise SemanticSearchError(str(exc)) from exc
        if len(hits) > candidate_limit:
            raise SemanticSearchError("Qdrant returned more results than requested")

        unique_hits = _unique_decision_hits(hits, limit=validated_top_k)

        results = [
            _result_from_hit(hit, rank=rank)
            for rank, hit in enumerate(unique_hits, start=1)
        ]
        return {
            "sorgu": normalized_query,
            "top_k": validated_top_k,
            "aranan_aday_chunk_sayisi": candidate_limit,
            "minimum_benzerlik_skoru": validated_min_score,
            "filtreler": validated_filters,
            "sonuc_sayisi": len(results),
            "yeterli_sonuc_bulundu": bool(results),
            "embedding_modeli": self.embedding_client.model,
            "koleksiyon": self.vector_store.collection_name,
            "sure_ms": round((time.perf_counter() - started) * 1_000, 3),
            "uyari": LEGAL_NOTICE,
            "sonuclar": results,
        }
