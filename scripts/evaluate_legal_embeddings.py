"""Evaluate LM Studio embeddings on real Yargitay chunks and legal queries."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, Sequence

from lmstudio_embeddings import (
    DEFAULT_BASE_URL,
    DEFAULT_EMBEDDING_MODEL,
    EmbeddingClientError,
    LMStudioEmbeddingClient,
    rank_by_similarity,
    vector_norm,
)


EVALUATION_VERSION = "1.0"


class EmbeddingEvaluationError(RuntimeError):
    """Raised when the legal embedding evaluation cannot be trusted."""


@dataclass(frozen=True)
class EvaluationCase:
    case_id: str
    query: str
    expected_chunk_id: str


DEFAULT_CANDIDATE_CHUNK_IDS = (
    "d1113966700:c0001",
    "d581878400:c0001",
    "d480864200:c0001",
)

DEFAULT_EVALUATION_CASES = (
    EvaluationCase(
        "gecersiz_fesih_ise_iade",
        (
            "İşveren belirsiz süreli iş sözleşmemi geçerli bir neden göstermeden "
            "feshetti. İşe iade ve işe başlatmama tazminatı talep edebilir miyim?"
        ),
        "d1113966700:c0001",
    ),
    EvaluationCase(
        "tapu_iptali_tescil",
        (
            "Belediyeden bedelini ödeyerek satın aldığım taşınmaz payının tapusu "
            "verilmedi. Tapu kaydının iptali ve adıma tescilini istiyorum."
        ),
        "d581878400:c0001",
    ),
    EvaluationCase(
        "uyusturucu_ticareti",
        (
            "Uyuşturucu madde ticareti suçunda tanık dinlenmeden ve eksik "
            "soruşturmayla mahkûmiyet kararı verilmiş. Temyizde nasıl değerlendirilir?"
        ),
        "d480864200:c0001",
    ),
)


class EmbeddingClientProtocol(Protocol):
    model: str
    base_url: str

    def ensure_model_available(self) -> tuple[str, ...]: ...

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]: ...


def _vector_sha256(vector: Sequence[float]) -> str:
    packed = struct.pack(f"<{len(vector)}d", *(float(value) for value in vector))
    return hashlib.sha256(packed).hexdigest()


def _preview(text: str, limit: int = 180) -> str:
    compact = " ".join(text.split())
    return compact if len(compact) <= limit else compact[: limit - 1] + "…"


def _validate_chunk_record(record: Any, *, line_number: int) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise EmbeddingEvaluationError(
            f"Chunk record at line {line_number} is not an object"
        )
    required_strings = (
        "id",
        "karar_id",
        "chunk_metni",
        "chunk_metni_sha256",
        "daire",
        "esas_no",
        "karar_no",
        "karar_tarihi",
    )
    for field in required_strings:
        if not isinstance(record.get(field), str) or not record[field].strip():
            raise EmbeddingEvaluationError(
                f"Missing {field!r} at chunk line {line_number}"
            )
    text = record["chunk_metni"]
    if record.get("karakter_sayisi") != len(text):
        raise EmbeddingEvaluationError(
            f"Chunk length mismatch at line {line_number}"
        )
    actual_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if record["chunk_metni_sha256"] != actual_hash:
        raise EmbeddingEvaluationError(
            f"Chunk hash mismatch at line {line_number}"
        )
    if not isinstance(record.get("veri_kalite_uyarilari"), list):
        raise EmbeddingEvaluationError(
            f"Invalid quality warnings at line {line_number}"
        )
    return dict(record)


def load_candidate_chunks(
    chunk_path: Path,
    candidate_ids: Sequence[str] = DEFAULT_CANDIDATE_CHUNK_IDS,
    *,
    expected_chunk_count: int | None = None,
) -> tuple[dict[str, dict[str, Any]], int]:
    """Load exact real chunks while validating the complete JSONL container."""
    if not chunk_path.is_file():
        raise EmbeddingEvaluationError(f"Chunk JSONL does not exist: {chunk_path}")
    requested_ids = tuple(candidate_ids)
    if not requested_ids or len(requested_ids) != len(set(requested_ids)):
        raise EmbeddingEvaluationError(
            "Candidate chunk ids must be non-empty and unique"
        )

    requested = set(requested_ids)
    found: dict[str, dict[str, Any]] = {}
    record_count = 0
    try:
        with chunk_path.open("r", encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, start=1):
                if not line.strip():
                    raise EmbeddingEvaluationError(
                        f"Blank JSONL line at {line_number}"
                    )
                try:
                    raw_record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise EmbeddingEvaluationError(
                        f"Invalid JSON at line {line_number}: {exc.msg}"
                    ) from exc
                record_count += 1
                if not isinstance(raw_record, dict):
                    raise EmbeddingEvaluationError(
                        f"Chunk record at line {line_number} is not an object"
                    )
                chunk_id = raw_record.get("id")
                if chunk_id in requested:
                    if chunk_id in found:
                        raise EmbeddingEvaluationError(
                            f"Duplicate requested chunk id: {chunk_id}"
                        )
                    found[chunk_id] = _validate_chunk_record(
                        raw_record, line_number=line_number
                    )
    except UnicodeDecodeError as exc:
        raise EmbeddingEvaluationError("Chunk JSONL is not valid UTF-8") from exc

    if expected_chunk_count is not None and record_count != expected_chunk_count:
        raise EmbeddingEvaluationError(
            f"Chunk count mismatch: expected {expected_chunk_count}, got {record_count}"
        )
    missing = requested - set(found)
    if missing:
        raise EmbeddingEvaluationError(
            f"Requested chunks were not found: {', '.join(sorted(missing))}"
        )
    return {chunk_id: found[chunk_id] for chunk_id in requested_ids}, record_count


def _validate_cases(
    cases: Sequence[EvaluationCase], candidate_ids: set[str]
) -> tuple[EvaluationCase, ...]:
    validated = tuple(cases)
    if not validated:
        raise EmbeddingEvaluationError("At least one evaluation case is required")
    case_ids: set[str] = set()
    for case in validated:
        if not case.case_id or case.case_id in case_ids:
            raise EmbeddingEvaluationError(
                f"Evaluation case id is empty or duplicated: {case.case_id!r}"
            )
        if not isinstance(case.query, str) or not case.query.strip():
            raise EmbeddingEvaluationError(
                f"Evaluation query is empty for case {case.case_id}"
            )
        if case.expected_chunk_id not in candidate_ids:
            raise EmbeddingEvaluationError(
                f"Expected chunk is not a candidate for case {case.case_id}: "
                f"{case.expected_chunk_id}"
            )
        case_ids.add(case.case_id)
    return validated


def evaluate_cases(
    client: EmbeddingClientProtocol,
    candidates: dict[str, dict[str, Any]],
    cases: Sequence[EvaluationCase] = DEFAULT_EVALUATION_CASES,
) -> dict[str, Any]:
    """Embed all queries/chunks in one batch and compare cosine similarities."""
    validated_cases = _validate_cases(cases, set(candidates))
    if len(candidates) < 2:
        raise EmbeddingEvaluationError(
            "At least two candidate chunks are required for relevance comparison"
        )

    try:
        available_models = client.ensure_model_available()
    except EmbeddingClientError as exc:
        raise EmbeddingEvaluationError(str(exc)) from exc

    candidate_ids = list(candidates)
    input_texts = [case.query for case in validated_cases] + [
        candidates[chunk_id]["chunk_metni"] for chunk_id in candidate_ids
    ]
    try:
        vectors = client.embed_texts(input_texts)
    except EmbeddingClientError as exc:
        raise EmbeddingEvaluationError(str(exc)) from exc
    if len(vectors) != len(input_texts):
        raise EmbeddingEvaluationError(
            "Embedding client returned a vector count mismatch"
        )
    dimensions = {len(vector) for vector in vectors}
    if len(dimensions) != 1 or not dimensions or next(iter(dimensions)) < 1:
        raise EmbeddingEvaluationError("Embedding vector dimensions are inconsistent")
    dimension = next(iter(dimensions))

    query_vectors = vectors[: len(validated_cases)]
    candidate_vector_values = vectors[len(validated_cases) :]
    candidate_vectors = dict(zip(candidate_ids, candidate_vector_values))
    candidate_embedding_info = {
        chunk_id: {
            "embedding_sha256": _vector_sha256(candidate_vectors[chunk_id]),
            "vector_norm": round(vector_norm(candidate_vectors[chunk_id]), 8),
        }
        for chunk_id in candidate_ids
    }

    case_results: list[dict[str, Any]] = []
    margins: list[float] = []
    for case, query_vector in zip(validated_cases, query_vectors):
        try:
            ranking = rank_by_similarity(query_vector, candidate_vectors)
        except EmbeddingClientError as exc:
            raise EmbeddingEvaluationError(str(exc)) from exc
        score_by_id = dict(ranking)
        expected_score = score_by_id[case.expected_chunk_id]
        irrelevant_scores = [
            score
            for chunk_id, score in ranking
            if chunk_id != case.expected_chunk_id
        ]
        best_irrelevant_score = max(irrelevant_scores)
        margin = expected_score - best_irrelevant_score
        margins.append(margin)
        case_results.append(
            {
                "case_id": case.case_id,
                "query": case.query,
                "query_embedding_sha256": _vector_sha256(query_vector),
                "query_vector_norm": round(vector_norm(query_vector), 8),
                "expected_chunk_id": case.expected_chunk_id,
                "top_chunk_id": ranking[0][0],
                "top_match_correct": ranking[0][0] == case.expected_chunk_id,
                "expected_similarity": round(expected_score, 6),
                "best_irrelevant_similarity": round(
                    best_irrelevant_score, 6
                ),
                "similarity_margin": round(margin, 6),
                "ranking": [
                    {
                        "rank": rank,
                        "chunk_id": chunk_id,
                        "similarity": round(score, 6),
                        "is_expected": chunk_id == case.expected_chunk_id,
                        "daire": candidates[chunk_id]["daire"],
                        "esas_no": candidates[chunk_id]["esas_no"],
                        "karar_no": candidates[chunk_id]["karar_no"],
                        "karar_tarihi": candidates[chunk_id]["karar_tarihi"],
                    }
                    for rank, (chunk_id, score) in enumerate(ranking, start=1)
                ],
            }
        )

    correct_count = sum(result["top_match_correct"] for result in case_results)
    candidate_details = [
        {
            "chunk_id": chunk_id,
            "karar_id": record["karar_id"],
            "daire": record["daire"],
            "esas_no": record["esas_no"],
            "karar_no": record["karar_no"],
            "karar_tarihi": record["karar_tarihi"],
            "karakter_sayisi": record["karakter_sayisi"],
            "chunk_metni_sha256": record["chunk_metni_sha256"],
            "veri_kalite_uyarilari": record["veri_kalite_uyarilari"],
            "onizleme": _preview(record["chunk_metni"]),
            **candidate_embedding_info[chunk_id],
        }
        for chunk_id, record in candidates.items()
    ]
    return {
        "evaluation_version": EVALUATION_VERSION,
        "server": {
            "base_url": client.base_url,
            "available_model_ids": list(available_models),
        },
        "embedding": {
            "model": client.model,
            "dimension": dimension,
            "batch_input_count": len(input_texts),
            "query_count": len(validated_cases),
            "candidate_count": len(candidates),
            "similarity_method": "cosine",
        },
        "candidates": candidate_details,
        "cases": case_results,
        "summary": {
            "top1_correct": correct_count,
            "top1_total": len(case_results),
            "top1_accuracy_percent": round(
                correct_count * 100 / len(case_results), 2
            ),
            "all_expected_above_irrelevant": all(
                result["similarity_margin"] > 0 for result in case_results
            ),
            "mean_similarity_margin": round(statistics.mean(margins), 6),
            "minimum_similarity_margin": round(min(margins), 6),
        },
    }


def run_evaluation(
    chunk_path: Path,
    output_path: Path,
    *,
    base_url: str = DEFAULT_BASE_URL,
    model: str = DEFAULT_EMBEDDING_MODEL,
    expected_chunk_count: int | None = 31544,
    client: EmbeddingClientProtocol | None = None,
    candidate_ids: Sequence[str] = DEFAULT_CANDIDATE_CHUNK_IDS,
    cases: Sequence[EvaluationCase] = DEFAULT_EVALUATION_CASES,
) -> dict[str, Any]:
    candidates, chunk_count = load_candidate_chunks(
        chunk_path,
        candidate_ids,
        expected_chunk_count=expected_chunk_count,
    )
    active_client = client or LMStudioEmbeddingClient(
        base_url=base_url,
        model=model,
    )
    report = evaluate_cases(active_client, candidates, cases)
    report["chunk_source"] = {
        "path": chunk_path.as_posix(),
        "records": chunk_count,
        "sha256": hashlib.sha256(chunk_path.read_bytes()).hexdigest(),
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_suffix(output_path.suffix + ".tmp")
    try:
        temporary_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(output_path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Embed real Yargitay chunks and legal queries with LM Studio, then "
            "compare relevant and irrelevant cosine similarities."
        )
    )
    parser.add_argument(
        "--chunks",
        type=Path,
        default=Path("data/processed/yargitay_chunks_1200_200.jsonl"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "data/processed/yargitay_embedding_evaluation_stats.json"
        ),
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--model", default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument("--expected-chunk-count", type=int, default=31544)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        report = run_evaluation(
            args.chunks,
            args.output,
            base_url=args.base_url,
            model=args.model,
            expected_chunk_count=args.expected_chunk_count,
        )
    except (EmbeddingEvaluationError, EmbeddingClientError) as exc:
        raise SystemExit(f"Embedding evaluation failed: {exc}") from exc

    print(
        json.dumps(
            {
                "model": report["embedding"]["model"],
                "dimension": report["embedding"]["dimension"],
                "summary": report["summary"],
                "cases": [
                    {
                        "case_id": case["case_id"],
                        "top_chunk_id": case["top_chunk_id"],
                        "top_match_correct": case["top_match_correct"],
                        "expected_similarity": case["expected_similarity"],
                        "best_irrelevant_similarity": case[
                            "best_irrelevant_similarity"
                        ],
                        "similarity_margin": case["similarity_margin"],
                    }
                    for case in report["cases"]
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"Evaluation report: {args.output}")


if __name__ == "__main__":
    main()
