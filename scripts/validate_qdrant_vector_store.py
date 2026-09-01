"""Run Day 14 Qdrant CRUD and similarity checks on real Yargitay chunks."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import struct
from importlib.metadata import version
from pathlib import Path
from typing import Any, Protocol, Sequence

from evaluate_legal_embeddings import (
    DEFAULT_CANDIDATE_CHUNK_IDS,
    DEFAULT_EVALUATION_CASES,
    EvaluationCase,
    load_candidate_chunks,
)
from lmstudio_embeddings import (
    DEFAULT_BASE_URL,
    DEFAULT_EMBEDDING_MODEL,
    EmbeddingClientError,
    LMStudioEmbeddingClient,
)
from qdrant_vector_store import (
    DEFAULT_COLLECTION_NAME,
    DEFAULT_VECTOR_SIZE,
    PAYLOAD_SCHEMA,
    QdrantVectorStore,
    VectorStoreError,
)


DAY14_VALIDATION_VERSION = "1.0"


class Day14ValidationError(RuntimeError):
    """Raised when the Day 14 vector-store validation cannot be trusted."""


class EmbeddingClientProtocol(Protocol):
    model: str
    base_url: str

    def ensure_model_available(self) -> tuple[str, ...]: ...

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]: ...


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _vector_sha256(vector: Sequence[float]) -> str:
    packed = struct.pack(f"<{len(vector)}d", *(float(value) for value in vector))
    return hashlib.sha256(packed).hexdigest()


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.tmp")
    try:
        with temporary_path.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _validate_embeddings(
    vectors: Sequence[Sequence[float]],
    *,
    expected_count: int,
    expected_vector_size: int,
) -> list[list[float]]:
    normalized = [list(vector) for vector in vectors]
    if len(normalized) != expected_count:
        raise Day14ValidationError(
            f"Embedding count mismatch: expected {expected_count}, got {len(normalized)}"
        )
    for item_index, vector in enumerate(normalized):
        if len(vector) != expected_vector_size:
            raise Day14ValidationError(
                f"Embedding dimension mismatch at index {item_index}: "
                f"expected {expected_vector_size}, got {len(vector)}"
            )
        squared_norm = 0.0
        for coordinate_index, coordinate in enumerate(vector):
            if isinstance(coordinate, bool) or not isinstance(coordinate, (int, float)):
                raise Day14ValidationError(
                    f"Non-numeric embedding coordinate {coordinate_index} at "
                    f"index {item_index}"
                )
            value = float(coordinate)
            if not math.isfinite(value):
                raise Day14ValidationError(
                    f"Non-finite embedding coordinate {coordinate_index} at "
                    f"index {item_index}"
                )
            vector[coordinate_index] = value
            squared_norm += value * value
        if squared_norm == 0.0:
            raise Day14ValidationError(f"Zero-norm embedding at index {item_index}")
    return normalized


def run_day14_validation(
    chunk_path: Path,
    database_path: Path,
    report_path: Path,
    *,
    expected_chunk_count: int = 31_544,
    expected_vector_size: int = DEFAULT_VECTOR_SIZE,
    collection_name: str = DEFAULT_COLLECTION_NAME,
    candidate_ids: Sequence[str] = DEFAULT_CANDIDATE_CHUNK_IDS,
    cases: Sequence[EvaluationCase] = DEFAULT_EVALUATION_CASES,
    embedding_client: EmbeddingClientProtocol | None = None,
    qdrant_client: Any | None = None,
) -> dict[str, Any]:
    """Validate collection schema plus upsert/read/delete/search operations."""
    ordered_candidate_ids = tuple(candidate_ids)
    ordered_cases = tuple(cases)
    candidates, source_record_count = load_candidate_chunks(
        chunk_path,
        ordered_candidate_ids,
        expected_chunk_count=expected_chunk_count,
    )
    if not ordered_cases:
        raise Day14ValidationError("At least one similarity case is required")
    if any(case.expected_chunk_id not in candidates for case in ordered_cases):
        raise Day14ValidationError("A similarity case references a missing candidate")

    client = embedding_client or LMStudioEmbeddingClient()
    try:
        available_models = client.ensure_model_available()
        input_texts = [case.query for case in ordered_cases] + [
            candidates[chunk_id]["chunk_metni"] for chunk_id in ordered_candidate_ids
        ]
        vectors = client.embed_texts(input_texts)
    except EmbeddingClientError as exc:
        raise Day14ValidationError(str(exc)) from exc
    normalized_vectors = _validate_embeddings(
        vectors,
        expected_count=len(input_texts),
        expected_vector_size=expected_vector_size,
    )
    query_vectors = normalized_vectors[: len(ordered_cases)]
    candidate_vectors = normalized_vectors[len(ordered_cases) :]

    store = QdrantVectorStore(
        path=database_path if qdrant_client is None else None,
        client=qdrant_client,
        collection_name=collection_name,
        vector_size=expected_vector_size,
        embedding_model=client.model,
    )
    try:
        collection = store.ensure_collection()
        count_before_upsert = store.count()
        upserted = store.upsert_chunks(
            [candidates[chunk_id] for chunk_id in ordered_candidate_ids],
            candidate_vectors,
        )
        count_after_upsert = store.count()
        if upserted != len(ordered_candidate_ids):
            raise Day14ValidationError("Not all sample chunks were upserted")
        if count_after_upsert < len(ordered_candidate_ids):
            raise Day14ValidationError("Collection count is smaller than the sample set")

        read_target_id = ordered_candidate_ids[0]
        retrieved = store.get_chunk(read_target_id)
        if retrieved is None:
            raise Day14ValidationError(f"Inserted chunk could not be read: {read_target_id}")
        if retrieved.get("chunk_metni_sha256") != candidates[read_target_id][
            "chunk_metni_sha256"
        ]:
            raise Day14ValidationError("Retrieved chunk hash does not match the source")

        case_results: list[dict[str, Any]] = []
        for case, query_vector in zip(ordered_cases, query_vectors):
            hits = store.search(query_vector, limit=len(ordered_candidate_ids))
            if len(hits) != len(ordered_candidate_ids):
                raise Day14ValidationError(
                    f"Search result count mismatch for case {case.case_id}"
                )
            top_match_correct = hits[0].chunk_id == case.expected_chunk_id
            case_results.append(
                {
                    "case_id": case.case_id,
                    "query": case.query,
                    "expected_chunk_id": case.expected_chunk_id,
                    "top_match_correct": top_match_correct,
                    "ranking": [
                        {
                            "rank": rank,
                            "chunk_id": hit.chunk_id,
                            "score": round(hit.score, 6),
                            "daire": hit.payload["daire"],
                            "esas_no": hit.payload["esas_no"],
                            "karar_no": hit.payload["karar_no"],
                        }
                        for rank, hit in enumerate(hits, start=1)
                    ],
                }
            )

        delete_target_id = ordered_candidate_ids[-1]
        if not store.delete_chunk(delete_target_id):
            raise Day14ValidationError("Delete target was unexpectedly absent")
        count_after_delete = store.count()
        delete_verified = (
            count_after_delete == count_after_upsert - 1
            and store.get_chunk(delete_target_id) is None
        )
        try:
            if not delete_verified:
                raise Day14ValidationError("Delete operation could not be verified")
        finally:
            store.upsert_chunks(
                [candidates[delete_target_id]],
                [candidate_vectors[-1]],
            )
        count_after_restore = store.count()
        restore_verified = (
            count_after_restore == count_after_upsert
            and store.get_chunk(delete_target_id) is not None
        )
        if not restore_verified:
            raise Day14ValidationError("Deleted sample could not be restored")

        correct_top_matches = sum(
            int(result["top_match_correct"]) for result in case_results
        )
        report = {
            "validation_version": DAY14_VALIDATION_VERSION,
            "qdrant": {
                "client_version": version("qdrant-client"),
                "mode": "local_persistent" if qdrant_client is None else "injected",
                "database_path": str(database_path),
            },
            "collection": collection,
            "chunk_source": {
                "path": str(chunk_path),
                "records": source_record_count,
                "sha256": _file_sha256(chunk_path),
            },
            "embedding": {
                "base_url": client.base_url,
                "model": client.model,
                "available_models": list(available_models),
                "dimension": expected_vector_size,
                "batch_input_count": len(input_texts),
                "candidate_vector_sha256": {
                    chunk_id: _vector_sha256(vector)
                    for chunk_id, vector in zip(
                        ordered_candidate_ids, candidate_vectors
                    )
                },
            },
            "operations": {
                "count_before_upsert": count_before_upsert,
                "upserted": upserted,
                "count_after_upsert": count_after_upsert,
                "read_target": read_target_id,
                "read_verified": True,
                "delete_target": delete_target_id,
                "count_after_delete": count_after_delete,
                "delete_verified": delete_verified,
                "count_after_restore": count_after_restore,
                "restore_verified": restore_verified,
            },
            "similarity_cases": case_results,
            "summary": {
                "similarity_case_count": len(case_results),
                "correct_top_matches": correct_top_matches,
                "top1_accuracy_percent": round(
                    100.0 * correct_top_matches / len(case_results), 2
                ),
                "all_crud_operations_verified": bool(
                    retrieved and delete_verified and restore_verified
                ),
                "payload_field_count": len(PAYLOAD_SCHEMA),
            },
        }
        _write_json_atomic(report_path, report)
        return report
    except VectorStoreError as exc:
        raise Day14ValidationError(str(exc)) from exc
    finally:
        store.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate the Day 14 local Qdrant collection and operations."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("data/processed/yargitay_chunks_1200_200.jsonl"),
    )
    parser.add_argument(
        "--database-path",
        type=Path,
        default=Path("data/vector_store/qdrant"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/processed/yargitay_qdrant_day14_stats.json"),
    )
    parser.add_argument("--collection", default=DEFAULT_COLLECTION_NAME)
    parser.add_argument("--expected-chunk-count", type=int, default=31_544)
    parser.add_argument("--vector-size", type=int, default=DEFAULT_VECTOR_SIZE)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--model", default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument("--timeout", type=float, default=60.0)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    embedding_client = LMStudioEmbeddingClient(
        base_url=args.base_url,
        model=args.model,
        timeout_seconds=args.timeout,
    )
    try:
        report = run_day14_validation(
            args.input,
            args.database_path,
            args.output,
            expected_chunk_count=args.expected_chunk_count,
            expected_vector_size=args.vector_size,
            collection_name=args.collection,
            embedding_client=embedding_client,
        )
    except Day14ValidationError as exc:
        raise SystemExit(f"Day 14 validation failed: {exc}") from exc

    print(
        json.dumps(
            {
                "collection": report["collection"]["name"],
                "vector_size": report["collection"]["vector_size"],
                "distance": report["collection"]["distance"],
                "points": report["operations"]["count_after_restore"],
                "top1_accuracy_percent": report["summary"][
                    "top1_accuracy_percent"
                ],
                "crud_verified": report["summary"][
                    "all_crud_operations_verified"
                ],
                "report": str(args.output),
                "report_sha256": _file_sha256(args.output),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
