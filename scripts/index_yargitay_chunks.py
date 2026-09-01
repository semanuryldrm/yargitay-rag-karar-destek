"""Batch, resume, and verify all Yargitay chunk embeddings in Qdrant."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from typing import Any, Protocol

from lmstudio_embeddings import (
    DEFAULT_BASE_URL,
    DEFAULT_EMBEDDING_MODEL,
    EmbeddingClientError,
    LMStudioEmbeddingClient,
)
from qdrant_vector_store import (
    DEFAULT_COLLECTION_NAME,
    DEFAULT_VECTOR_SIZE,
    QdrantVectorStore,
    VectorStoreError,
    build_chunk_payload,
)


DAY15_INDEXING_VERSION = "1.0"
STATE_SCHEMA_VERSION = 1
DEFAULT_INPUT_PATH = Path("data/processed/yargitay_chunks_1200_200.jsonl")
DEFAULT_DATABASE_PATH = Path("data/vector_store/qdrant")
DEFAULT_STATE_PATH = Path("data/processed/yargitay_qdrant_day15_state.json")
DEFAULT_REPORT_PATH = Path("data/processed/yargitay_qdrant_day15_stats.json")
DEFAULT_FAILURE_PATH = Path("logs/day15_embedding_failures.jsonl")
DEFAULT_EXPECTED_CHUNK_COUNT = 31_544
DEFAULT_BATCH_SIZE = 128
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_RETRY_DELAY_SECONDS = 2.0


class Day15IndexingError(RuntimeError):
    """Raised when a complete and trustworthy vector index cannot be produced."""


class EmbeddingClientProtocol(Protocol):
    model: str
    base_url: str

    def ensure_model_available(self) -> tuple[str, ...]: ...

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]: ...


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
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


def _append_jsonl(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _parse_json_line(raw_line: bytes, *, path: Path, line_number: int) -> dict[str, Any]:
    try:
        text = raw_line.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise Day15IndexingError(
            f"Chunk source is not valid UTF-8 at {path}:{line_number}"
        ) from exc
    if not text.strip():
        raise Day15IndexingError(f"Blank JSONL line at {path}:{line_number}")
    try:
        record = json.loads(text)
    except json.JSONDecodeError as exc:
        raise Day15IndexingError(
            f"Invalid JSON at {path}:{line_number}: {exc.msg}"
        ) from exc
    if not isinstance(record, dict):
        raise Day15IndexingError(
            f"Chunk record is not an object at {path}:{line_number}"
        )
    return record


def scan_chunk_source(
    path: Path,
    *,
    expected_chunk_count: int,
    embedding_model: str,
    vector_size: int,
) -> dict[str, Any]:
    """Validate every source record before any embedding request or Qdrant write."""
    if not path.is_file():
        raise Day15IndexingError(f"Chunk source does not exist: {path}")
    if (
        isinstance(expected_chunk_count, bool)
        or not isinstance(expected_chunk_count, int)
        or expected_chunk_count < 1
    ):
        raise Day15IndexingError("Expected chunk count must be a positive integer")

    digest = hashlib.sha256()
    seen_ids: set[str] = set()
    sample_indexes = {
        1,
        (expected_chunk_count + 1) // 2,
        expected_chunk_count,
    }
    samples: list[dict[str, str]] = []
    record_count = 0

    with path.open("rb") as stream:
        for line_number, raw_line in enumerate(stream, start=1):
            digest.update(raw_line)
            record = _parse_json_line(raw_line, path=path, line_number=line_number)
            try:
                payload = build_chunk_payload(
                    record,
                    embedding_model=embedding_model,
                    vector_size=vector_size,
                )
            except VectorStoreError as exc:
                raise Day15IndexingError(
                    f"Invalid chunk at {path}:{line_number}: {exc}"
                ) from exc
            chunk_id = payload["chunk_id"]
            if chunk_id in seen_ids:
                raise Day15IndexingError(
                    f"Duplicate chunk id at {path}:{line_number}: {chunk_id}"
                )
            seen_ids.add(chunk_id)
            record_count += 1
            if line_number in sample_indexes:
                samples.append(
                    {
                        "chunk_id": chunk_id,
                        "chunk_metni_sha256": payload["chunk_metni_sha256"],
                    }
                )

    if record_count != expected_chunk_count:
        raise Day15IndexingError(
            "Chunk source count mismatch: "
            f"expected {expected_chunk_count}, got {record_count}"
        )
    if len(samples) != len(sample_indexes):
        raise Day15IndexingError("Could not collect deterministic source samples")
    return {
        "path": str(path),
        "records": record_count,
        "unique_chunk_ids": len(seen_ids),
        "sha256": digest.hexdigest(),
        "verification_samples": samples,
    }


def _new_state(
    source: Mapping[str, Any],
    *,
    batch_size: int,
    collection_name: str,
    embedding_model: str,
    vector_size: int,
) -> dict[str, Any]:
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "source_sha256": source["sha256"],
        "source_records": source["records"],
        "batch_size": batch_size,
        "collection_name": collection_name,
        "embedding_model": embedding_model,
        "vector_size": vector_size,
        "next_line": 0,
        "indexed_chunks": 0,
        "successful_batches": 0,
        "failed_attempts": 0,
        "elapsed_seconds": 0.0,
        "completed": False,
        "last_completed_at": None,
        "last_error": None,
    }


def load_index_state(
    path: Path,
    source: Mapping[str, Any],
    *,
    batch_size: int,
    collection_name: str,
    embedding_model: str,
    vector_size: int,
) -> dict[str, Any]:
    """Load resume state and reject a state created for another index run."""
    expected = _new_state(
        source,
        batch_size=batch_size,
        collection_name=collection_name,
        embedding_model=embedding_model,
        vector_size=vector_size,
    )
    if not path.exists():
        return expected
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Day15IndexingError(f"Invalid Day 15 state file: {path}") from exc
    if not isinstance(state, dict):
        raise Day15IndexingError("Day 15 state root must be an object")

    configuration_fields = (
        "schema_version",
        "source_sha256",
        "source_records",
        "batch_size",
        "collection_name",
        "embedding_model",
        "vector_size",
    )
    for field in configuration_fields:
        if state.get(field) != expected[field]:
            raise Day15IndexingError(
                f"Day 15 state configuration mismatch for {field!r}"
            )

    integer_fields = (
        "next_line",
        "indexed_chunks",
        "successful_batches",
        "failed_attempts",
    )
    for field in integer_fields:
        value = state.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise Day15IndexingError(f"Invalid {field!r} in Day 15 state")
    if state["next_line"] != state["indexed_chunks"]:
        raise Day15IndexingError("Day 15 state line/indexed counts differ")
    if state["next_line"] > source["records"]:
        raise Day15IndexingError("Day 15 state exceeds the source record count")
    elapsed = state.get("elapsed_seconds")
    if isinstance(elapsed, bool) or not isinstance(elapsed, (int, float)) or elapsed < 0:
        raise Day15IndexingError("Invalid elapsed_seconds in Day 15 state")
    if not isinstance(state.get("completed"), bool):
        raise Day15IndexingError("Invalid completed flag in Day 15 state")
    if state["completed"] and state["next_line"] != source["records"]:
        raise Day15IndexingError("Day 15 state completion flag is inconsistent")
    return dict(state)


def _iter_batches(
    path: Path, *, start_line: int, batch_size: int
) -> Iterator[tuple[int, list[dict[str, Any]]]]:
    batch: list[dict[str, Any]] = []
    batch_start = start_line + 1
    with path.open("rb") as stream:
        for line_number, raw_line in enumerate(stream, start=1):
            if line_number <= start_line:
                continue
            batch.append(
                _parse_json_line(raw_line, path=path, line_number=line_number)
            )
            if len(batch) == batch_size:
                yield batch_start, batch
                batch = []
                batch_start = line_number + 1
        if batch:
            yield batch_start, batch


def _verify_source_samples(
    store: QdrantVectorStore, source: Mapping[str, Any]
) -> list[dict[str, Any]]:
    verified: list[dict[str, Any]] = []
    for sample in source["verification_samples"]:
        chunk_id = sample["chunk_id"]
        payload = store.get_chunk(chunk_id)
        matches = bool(
            payload
            and payload.get("chunk_metni_sha256") == sample["chunk_metni_sha256"]
        )
        verified.append({"chunk_id": chunk_id, "hash_matches": matches})
        if not matches:
            raise Day15IndexingError(
                f"Qdrant source-hash verification failed for {chunk_id}"
            )
    return verified


def run_day15_indexing(
    chunk_path: Path,
    database_path: Path,
    state_path: Path,
    report_path: Path,
    failure_path: Path,
    *,
    expected_chunk_count: int = DEFAULT_EXPECTED_CHUNK_COUNT,
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    retry_delay_seconds: float = DEFAULT_RETRY_DELAY_SECONDS,
    expected_vector_size: int = DEFAULT_VECTOR_SIZE,
    collection_name: str = DEFAULT_COLLECTION_NAME,
    embedding_client: EmbeddingClientProtocol | None = None,
    qdrant_client: Any | None = None,
    progress_callback: Callable[[Mapping[str, Any]], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    max_batches: int | None = None,
) -> dict[str, Any]:
    """Embed and upsert all chunks without skipping a failed batch."""
    if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size < 1:
        raise Day15IndexingError("Batch size must be a positive integer")
    if (
        isinstance(max_attempts, bool)
        or not isinstance(max_attempts, int)
        or max_attempts < 1
    ):
        raise Day15IndexingError("Max attempts must be a positive integer")
    if retry_delay_seconds < 0:
        raise Day15IndexingError("Retry delay cannot be negative")
    if max_batches is not None and (
        isinstance(max_batches, bool)
        or not isinstance(max_batches, int)
        or max_batches < 1
    ):
        raise Day15IndexingError("Max batches must be a positive integer")

    client = embedding_client or LMStudioEmbeddingClient()
    source = scan_chunk_source(
        chunk_path,
        expected_chunk_count=expected_chunk_count,
        embedding_model=client.model,
        vector_size=expected_vector_size,
    )
    state = load_index_state(
        state_path,
        source,
        batch_size=batch_size,
        collection_name=collection_name,
        embedding_model=client.model,
        vector_size=expected_vector_size,
    )
    try:
        available_models = client.ensure_model_available()
    except EmbeddingClientError as exc:
        raise Day15IndexingError(str(exc)) from exc

    store = QdrantVectorStore(
        path=database_path if qdrant_client is None else None,
        client=qdrant_client,
        collection_name=collection_name,
        vector_size=expected_vector_size,
        embedding_model=client.model,
    )
    run_started_at = _utc_now()
    processed_this_run = 0
    batches_this_run = 0
    try:
        collection = store.ensure_collection()
        count_before_run = store.count()
        if count_before_run < state["indexed_chunks"]:
            raise Day15IndexingError(
                "Qdrant count is smaller than the persisted indexed chunk count"
            )
        if state["completed"] and report_path.exists():
            if count_before_run != expected_chunk_count:
                raise Day15IndexingError(
                    "Completed state does not match the current Qdrant count"
                )
            _verify_source_samples(store, source)
            try:
                existing_report = json.loads(report_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise Day15IndexingError(
                    f"Invalid completed Day 15 report: {report_path}"
                ) from exc
            if not isinstance(existing_report, dict):
                raise Day15IndexingError("Completed Day 15 report must be an object")
            report_source = existing_report.get("source")
            report_summary = existing_report.get("summary")
            if (
                not isinstance(report_source, dict)
                or not isinstance(report_summary, dict)
                or report_source.get("sha256") != source["sha256"]
                or report_summary.get("indexed_chunks") != expected_chunk_count
                or report_summary.get("completed") is not True
            ):
                raise Day15IndexingError(
                    "Completed Day 15 report does not match the current index"
                )
            return existing_report

        for batch_start_line, records in _iter_batches(
            chunk_path,
            start_line=state["next_line"],
            batch_size=batch_size,
        ):
            batch_started = time.monotonic()
            chunk_ids = [record.get("id") for record in records]
            last_error: Exception | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    vectors = client.embed_texts(
                        [record["chunk_metni"] for record in records]
                    )
                    if len(vectors) != len(records):
                        raise Day15IndexingError(
                            "Embedding result count does not match the batch"
                        )
                    store.upsert_chunks(records, vectors)
                    last_error = None
                    break
                except Exception as exc:  # noqa: BLE001 - logged, retried, then raised
                    last_error = exc
                    state["failed_attempts"] += 1
                    state["last_error"] = {
                        "batch_start_line": batch_start_line,
                        "batch_end_line": batch_start_line + len(records) - 1,
                        "attempt": attempt,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "failed_at": _utc_now(),
                    }
                    _append_jsonl(
                        failure_path,
                        {
                            **state["last_error"],
                            "chunk_ids": chunk_ids,
                        },
                    )
                    _write_json_atomic(state_path, state)
                    if attempt < max_attempts:
                        sleep(retry_delay_seconds)

            state["elapsed_seconds"] = round(
                float(state["elapsed_seconds"]) + time.monotonic() - batch_started,
                6,
            )
            if last_error is not None:
                _write_json_atomic(state_path, state)
                raise Day15IndexingError(
                    "Embedding/index batch failed after "
                    f"{max_attempts} attempts at source lines "
                    f"{batch_start_line}-{batch_start_line + len(records) - 1}: "
                    f"{last_error}"
                ) from last_error

            state["next_line"] += len(records)
            state["indexed_chunks"] = state["next_line"]
            state["successful_batches"] += 1
            state["last_completed_at"] = _utc_now()
            state["last_error"] = None
            processed_this_run += len(records)
            batches_this_run += 1
            _write_json_atomic(state_path, state)
            if progress_callback is not None:
                progress_callback(dict(state))
            if max_batches is not None and batches_this_run >= max_batches:
                break

        if state["indexed_chunks"] < expected_chunk_count:
            return {
                "completed": False,
                "indexed_chunks": state["indexed_chunks"],
                "remaining_chunks": expected_chunk_count - state["indexed_chunks"],
                "processed_this_run": processed_this_run,
                "batches_this_run": batches_this_run,
                "state_path": str(state_path),
            }

        count_after_run = store.count()
        if count_after_run != expected_chunk_count:
            raise Day15IndexingError(
                "Final Qdrant count mismatch: "
                f"expected {expected_chunk_count}, got {count_after_run}"
            )
        verified_samples = _verify_source_samples(store, source)
        state["completed"] = True
        state["last_completed_at"] = _utc_now()
        state["last_error"] = None
        _write_json_atomic(state_path, state)

        elapsed_seconds = float(state["elapsed_seconds"])
        report = {
            "indexing_version": DAY15_INDEXING_VERSION,
            "run": {
                "started_at": run_started_at,
                "completed_at": state["last_completed_at"],
                "resumed_from_line": state["indexed_chunks"] - processed_this_run,
                "processed_this_run": processed_this_run,
                "batches_this_run": batches_this_run,
            },
            "source": source,
            "embedding": {
                "base_url": client.base_url,
                "model": client.model,
                "available_models": list(available_models),
                "dimension": expected_vector_size,
            },
            "qdrant": {
                "client_version": version("qdrant-client"),
                "mode": "local_persistent" if qdrant_client is None else "injected",
                "database_path": str(database_path),
                "collection": collection,
                "count_before_run": count_before_run,
                "count_after_run": count_after_run,
            },
            "batch_processing": {
                "batch_size": batch_size,
                "max_attempts": max_attempts,
                "retry_delay_seconds": retry_delay_seconds,
                "successful_batches": state["successful_batches"],
                "failed_attempts": state["failed_attempts"],
                "unresolved_failed_batches": 0,
                "elapsed_seconds": elapsed_seconds,
                "chunks_per_second": (
                    round(expected_chunk_count / elapsed_seconds, 3)
                    if elapsed_seconds
                    else None
                ),
                "state_path": str(state_path),
                "failure_path": str(failure_path),
            },
            "verification": {
                "exact_collection_count": count_after_run == expected_chunk_count,
                "unique_source_chunk_ids": source["unique_chunk_ids"],
                "sample_payload_hashes": verified_samples,
                "all_sample_hashes_match": all(
                    item["hash_matches"] for item in verified_samples
                ),
            },
            "summary": {
                "source_chunks": expected_chunk_count,
                "indexed_chunks": count_after_run,
                "completion_percent": 100.0,
                "completed": True,
            },
        }
        _write_json_atomic(report_path, report)
        return report
    except VectorStoreError as exc:
        raise Day15IndexingError(str(exc)) from exc
    finally:
        store.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Embed all cleaned Yargitay chunks in resumable batches and index them "
            "in the local Qdrant collection."
        )
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT_PATH)
    parser.add_argument("--database-path", type=Path, default=DEFAULT_DATABASE_PATH)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--failures", type=Path, default=DEFAULT_FAILURE_PATH)
    parser.add_argument(
        "--expected-chunks", type=int, default=DEFAULT_EXPECTED_CHUNK_COUNT
    )
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--max-attempts", type=int, default=DEFAULT_MAX_ATTEMPTS)
    parser.add_argument(
        "--retry-delay-seconds",
        type=float,
        default=DEFAULT_RETRY_DELAY_SECONDS,
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--model", default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument("--vector-size", type=int, default=DEFAULT_VECTOR_SIZE)
    parser.add_argument("--collection", default=DEFAULT_COLLECTION_NAME)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    client = LMStudioEmbeddingClient(base_url=args.base_url, model=args.model)

    def show_progress(state: Mapping[str, Any]) -> None:
        indexed = state["indexed_chunks"]
        percent = 100.0 * indexed / args.expected_chunks
        print(
            f"Indexed {indexed}/{args.expected_chunks} chunks "
            f"({percent:.2f}%); successful batches={state['successful_batches']}; "
            f"failed attempts={state['failed_attempts']}",
            flush=True,
        )

    try:
        result = run_day15_indexing(
            args.input,
            args.database_path,
            args.state,
            args.output,
            args.failures,
            expected_chunk_count=args.expected_chunks,
            batch_size=args.batch_size,
            max_attempts=args.max_attempts,
            retry_delay_seconds=args.retry_delay_seconds,
            expected_vector_size=args.vector_size,
            collection_name=args.collection,
            embedding_client=client,
            progress_callback=show_progress,
        )
    except (Day15IndexingError, EmbeddingClientError, OSError) as exc:
        raise SystemExit(f"Day 15 indexing failed: {exc}") from exc

    print(
        "Day 15 indexing completed: "
        f"{result['summary']['indexed_chunks']} chunks in Qdrant; "
        f"report={args.output}"
    )


if __name__ == "__main__":
    main()
