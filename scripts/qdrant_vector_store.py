"""Validated local Qdrant vector store for Yargitay decision chunks."""

from __future__ import annotations

import hashlib
import math
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.http import models


DEFAULT_COLLECTION_NAME = "yargitay_karar_parcalari"
DEFAULT_VECTOR_SIZE = 768
DEFAULT_DISTANCE = models.Distance.COSINE
COLLECTION_SCHEMA_VERSION = "1.0"
POINT_ID_NAMESPACE = uuid.UUID("d02d5813-8ae9-4a1e-a638-b78c45eae610")

PAYLOAD_SCHEMA: dict[str, str] = {
    "chunk_id": "keyword",
    "karar_id": "keyword",
    "chunk_sirasi": "integer",
    "toplam_chunk": "integer",
    "daire": "keyword",
    "karar_turu": "keyword",
    "esas_no": "keyword",
    "karar_no": "keyword",
    "karar_tarihi": "keyword",
    "baslik": "text",
    "chunk_metni": "text",
    "chunk_metni_sha256": "keyword",
    "veri_kalite_uyarilari": "keyword[]",
    "veri_kalite_durumu": "keyword",
    "metin_2000_karakter_sinirinda": "bool",
    "kaynak": "keyword",
    "kaynak_url": "keyword",
    "kaynak_lisans": "keyword",
    "kaynak_kayit_id": "keyword",
    "embedding_model": "keyword",
    "embedding_dimension": "integer",
    "koleksiyon_sema_surumu": "keyword",
}

REQUIRED_CHUNK_STRING_FIELDS = (
    "id",
    "karar_id",
    "daire",
    "karar_turu",
    "esas_no",
    "karar_no",
    "karar_tarihi",
    "baslik",
    "chunk_metni",
    "chunk_metni_sha256",
    "veri_kalite_durumu",
    "kaynak",
    "kaynak_url",
    "kaynak_lisans",
    "kaynak_kayit_id",
)


class VectorStoreError(RuntimeError):
    """Raised when vector-store data or collection state is unsafe to use."""


@dataclass(frozen=True)
class SearchHit:
    """One validated nearest-neighbour result."""

    chunk_id: str
    score: float
    payload: dict[str, Any]


def point_id_for_chunk(chunk_id: str) -> str:
    """Map an arbitrary chunk id to a stable Qdrant-compatible UUID."""
    if not isinstance(chunk_id, str) or not chunk_id.strip():
        raise VectorStoreError("Chunk id is empty")
    return str(uuid.uuid5(POINT_ID_NAMESPACE, chunk_id.strip()))


def validate_vector(vector: Sequence[float], *, expected_size: int) -> list[float]:
    """Return a finite, non-zero vector with the configured dimension."""
    if isinstance(vector, (str, bytes)):
        raise VectorStoreError("Vector must be a numeric sequence")
    normalized = list(vector)
    if len(normalized) != expected_size:
        raise VectorStoreError(
            f"Vector dimension mismatch: expected {expected_size}, got {len(normalized)}"
        )
    squared_norm = 0.0
    for index, coordinate in enumerate(normalized):
        if isinstance(coordinate, bool) or not isinstance(coordinate, (int, float)):
            raise VectorStoreError(f"Vector coordinate {index} is not numeric")
        number = float(coordinate)
        if not math.isfinite(number):
            raise VectorStoreError(f"Vector coordinate {index} is not finite")
        normalized[index] = number
        squared_norm += number * number
    if squared_norm == 0.0:
        raise VectorStoreError("Vector has zero norm")
    return normalized


def build_chunk_payload(
    chunk: Mapping[str, Any],
    *,
    embedding_model: str,
    vector_size: int,
) -> dict[str, Any]:
    """Validate a chunk and create the collection's explicit payload shape."""
    if not isinstance(chunk, Mapping):
        raise VectorStoreError("Chunk record is not an object")
    if not isinstance(embedding_model, str) or not embedding_model.strip():
        raise VectorStoreError("Embedding model id is empty")
    for field in REQUIRED_CHUNK_STRING_FIELDS:
        value = chunk.get(field)
        if not isinstance(value, str) or not value.strip():
            raise VectorStoreError(f"Chunk field {field!r} is empty or not text")

    chunk_order = chunk.get("chunk_sirasi")
    total_chunks = chunk.get("toplam_chunk")
    if (
        isinstance(chunk_order, bool)
        or not isinstance(chunk_order, int)
        or chunk_order < 1
    ):
        raise VectorStoreError("chunk_sirasi must be a positive integer")
    if (
        isinstance(total_chunks, bool)
        or not isinstance(total_chunks, int)
        or total_chunks < chunk_order
    ):
        raise VectorStoreError("toplam_chunk must be an integer >= chunk_sirasi")

    warnings = chunk.get("veri_kalite_uyarilari")
    if not isinstance(warnings, list) or not all(
        isinstance(item, str) and item.strip() for item in warnings
    ):
        raise VectorStoreError("veri_kalite_uyarilari must be a list of texts")
    truncated = chunk.get("metin_2000_karakter_sinirinda")
    if not isinstance(truncated, bool):
        raise VectorStoreError("metin_2000_karakter_sinirinda must be boolean")

    text = chunk["chunk_metni"]
    actual_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if chunk["chunk_metni_sha256"] != actual_hash:
        raise VectorStoreError(f"Chunk text hash mismatch: {chunk['id']}")
    if chunk.get("karakter_sayisi") != len(text):
        raise VectorStoreError(f"Chunk text length mismatch: {chunk['id']}")

    return {
        "chunk_id": chunk["id"],
        "karar_id": chunk["karar_id"],
        "chunk_sirasi": chunk_order,
        "toplam_chunk": total_chunks,
        "daire": chunk["daire"],
        "karar_turu": chunk["karar_turu"],
        "esas_no": chunk["esas_no"],
        "karar_no": chunk["karar_no"],
        "karar_tarihi": chunk["karar_tarihi"],
        "baslik": chunk["baslik"],
        "chunk_metni": text,
        "chunk_metni_sha256": actual_hash,
        "veri_kalite_uyarilari": list(warnings),
        "veri_kalite_durumu": chunk["veri_kalite_durumu"],
        "metin_2000_karakter_sinirinda": truncated,
        "kaynak": chunk["kaynak"],
        "kaynak_url": chunk["kaynak_url"],
        "kaynak_lisans": chunk["kaynak_lisans"],
        "kaynak_kayit_id": chunk["kaynak_kayit_id"],
        "embedding_model": embedding_model.strip(),
        "embedding_dimension": vector_size,
        "koleksiyon_sema_surumu": COLLECTION_SCHEMA_VERSION,
    }


class QdrantVectorStore:
    """Application boundary around a local or injected Qdrant client."""

    def __init__(
        self,
        *,
        path: Path | str | None = None,
        client: QdrantClient | None = None,
        collection_name: str = DEFAULT_COLLECTION_NAME,
        vector_size: int = DEFAULT_VECTOR_SIZE,
        embedding_model: str,
    ) -> None:
        if client is None and path is None:
            raise VectorStoreError("Either a Qdrant client or a local path is required")
        if not isinstance(collection_name, str) or not collection_name.strip():
            raise VectorStoreError("Collection name is empty")
        if isinstance(vector_size, bool) or not isinstance(vector_size, int) or vector_size < 1:
            raise VectorStoreError("Vector size must be a positive integer")
        if not isinstance(embedding_model, str) or not embedding_model.strip():
            raise VectorStoreError("Embedding model id is empty")

        self.collection_name = collection_name.strip()
        self.vector_size = vector_size
        self.embedding_model = embedding_model.strip()
        self.path = Path(path) if path is not None else None
        self._owns_client = client is None
        self.client = client or QdrantClient(path=str(self.path))

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> "QdrantVectorStore":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()

    def _collection_metadata(self) -> dict[str, Any]:
        return {
            "application": "yargitay-rag-karar-destek",
            "schema_version": COLLECTION_SCHEMA_VERSION,
            "embedding_model": self.embedding_model,
            "vector_size": self.vector_size,
            "distance": DEFAULT_DISTANCE.value,
            "payload_schema": PAYLOAD_SCHEMA,
        }

    def ensure_collection(self) -> dict[str, Any]:
        """Create the collection or reject an incompatible existing schema."""
        created = False
        if not self.client.collection_exists(self.collection_name):
            created = self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=models.VectorParams(
                    size=self.vector_size,
                    distance=DEFAULT_DISTANCE,
                ),
                on_disk_payload=True,
                metadata=self._collection_metadata(),
            )
            if not created:
                raise VectorStoreError(
                    f"Qdrant did not create collection {self.collection_name!r}"
                )

        info = self.client.get_collection(self.collection_name)
        vector_config = info.config.params.vectors
        if not isinstance(vector_config, models.VectorParams):
            raise VectorStoreError("Named or missing vector configuration is unsupported")
        if vector_config.size != self.vector_size:
            raise VectorStoreError(
                "Existing collection vector size mismatch: "
                f"expected {self.vector_size}, got {vector_config.size}"
            )
        if vector_config.distance != DEFAULT_DISTANCE:
            raise VectorStoreError(
                "Existing collection distance mismatch: "
                f"expected {DEFAULT_DISTANCE.value}, got {vector_config.distance.value}"
            )

        metadata = info.config.metadata or {}
        expected_metadata = self._collection_metadata()
        for field in ("schema_version", "embedding_model", "vector_size", "distance"):
            if metadata.get(field) != expected_metadata[field]:
                raise VectorStoreError(
                    f"Existing collection metadata mismatch for {field!r}: "
                    f"expected {expected_metadata[field]!r}, got {metadata.get(field)!r}"
                )
        if metadata.get("payload_schema") != PAYLOAD_SCHEMA:
            raise VectorStoreError("Existing collection payload schema is incompatible")

        return {
            "created": bool(created),
            "name": self.collection_name,
            "vector_size": vector_config.size,
            "distance": vector_config.distance.value,
            "embedding_model": metadata["embedding_model"],
            "schema_version": metadata["schema_version"],
            "payload_schema": dict(PAYLOAD_SCHEMA),
        }

    def upsert_chunks(
        self,
        chunks: Sequence[Mapping[str, Any]],
        vectors: Sequence[Sequence[float]],
    ) -> int:
        normalized_chunks = list(chunks)
        normalized_vectors = list(vectors)
        if not normalized_chunks:
            raise VectorStoreError("At least one chunk is required for upsert")
        if len(normalized_chunks) != len(normalized_vectors):
            raise VectorStoreError(
                "Chunk and vector counts differ: "
                f"{len(normalized_chunks)} != {len(normalized_vectors)}"
            )
        chunk_ids = [chunk.get("id") for chunk in normalized_chunks]
        if len(chunk_ids) != len(set(chunk_ids)):
            raise VectorStoreError("Upsert batch contains duplicate chunk ids")

        points: list[models.PointStruct] = []
        for chunk, vector in zip(normalized_chunks, normalized_vectors):
            payload = build_chunk_payload(
                chunk,
                embedding_model=self.embedding_model,
                vector_size=self.vector_size,
            )
            points.append(
                models.PointStruct(
                    id=point_id_for_chunk(payload["chunk_id"]),
                    vector=validate_vector(vector, expected_size=self.vector_size),
                    payload=payload,
                )
            )
        result = self.client.upsert(
            collection_name=self.collection_name,
            points=points,
            wait=True,
        )
        if result.status != models.UpdateStatus.COMPLETED:
            raise VectorStoreError(f"Qdrant upsert did not complete: {result.status}")
        return len(points)

    def get_chunk(self, chunk_id: str) -> dict[str, Any] | None:
        records = self.client.retrieve(
            collection_name=self.collection_name,
            ids=[point_id_for_chunk(chunk_id)],
            with_payload=True,
            with_vectors=False,
        )
        if not records:
            return None
        if len(records) != 1 or not isinstance(records[0].payload, dict):
            raise VectorStoreError(f"Unexpected Qdrant retrieval result for {chunk_id}")
        payload = dict(records[0].payload)
        if payload.get("chunk_id") != chunk_id:
            raise VectorStoreError(f"Retrieved payload id mismatch for {chunk_id}")
        return payload

    def delete_chunk(self, chunk_id: str) -> bool:
        if self.get_chunk(chunk_id) is None:
            return False
        result = self.client.delete(
            collection_name=self.collection_name,
            points_selector=models.PointIdsList(points=[point_id_for_chunk(chunk_id)]),
            wait=True,
        )
        if result.status != models.UpdateStatus.COMPLETED:
            raise VectorStoreError(f"Qdrant delete did not complete: {result.status}")
        if self.get_chunk(chunk_id) is not None:
            raise VectorStoreError(f"Deleted chunk is still retrievable: {chunk_id}")
        return True

    def search(
        self,
        query_vector: Sequence[float],
        *,
        limit: int = 5,
        query_filter: models.Filter | None = None,
    ) -> tuple[SearchHit, ...]:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise VectorStoreError("Search limit must be a positive integer")
        response = self.client.query_points(
            collection_name=self.collection_name,
            query=validate_vector(query_vector, expected_size=self.vector_size),
            query_filter=query_filter,
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
        hits: list[SearchHit] = []
        seen_chunk_ids: set[str] = set()
        for point in response.points:
            if not isinstance(point.payload, dict):
                raise VectorStoreError("Search result has no payload")
            chunk_id = point.payload.get("chunk_id")
            if not isinstance(chunk_id, str) or not chunk_id:
                raise VectorStoreError("Search result has no chunk_id")
            if chunk_id in seen_chunk_ids:
                raise VectorStoreError(f"Search returned duplicate chunk id: {chunk_id}")
            score = float(point.score)
            if not math.isfinite(score):
                raise VectorStoreError(f"Search score is not finite for {chunk_id}")
            hits.append(SearchHit(chunk_id, score, dict(point.payload)))
            seen_chunk_ids.add(chunk_id)
        return tuple(hits)

    def count(self) -> int:
        result = self.client.count(
            collection_name=self.collection_name,
            exact=True,
        )
        if result.count < 0:
            raise VectorStoreError("Qdrant returned a negative point count")
        return result.count
