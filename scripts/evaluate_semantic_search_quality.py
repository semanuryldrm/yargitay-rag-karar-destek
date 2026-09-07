"""Evaluate Day 17 semantic-search quality on the complete local index."""

from __future__ import annotations

import argparse
import json
import os
import statistics
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from chunk_yargitay_data import chunk_decision_record, load_cleaned_records
from lmstudio_embeddings import (
    DEFAULT_BASE_URL,
    DEFAULT_EMBEDDING_MODEL,
    LMStudioEmbeddingClient,
    cosine_similarity,
)
from qdrant_vector_store import (
    DEFAULT_COLLECTION_NAME,
    DEFAULT_VECTOR_SIZE,
    QdrantVectorStore,
    SearchHit,
)


EVALUATION_VERSION = "1.0"
DEFAULT_CLEAN_DATA = Path("data/processed/yargitay_clean_14870.jsonl")
DEFAULT_QDRANT_PATH = Path("data/vector_store/qdrant")
DEFAULT_OUTPUT = Path(
    "data/processed/yargitay_semantic_search_day17_stats.json"
)
DEFAULT_EXPECTED_DECISIONS = 14_870
DEFAULT_EXPECTED_POINTS = 31_544
SEARCH_CANDIDATE_LIMIT = 100
TOP_K_VALUES = (1, 3, 5, 10, 20)
THRESHOLD_VALUES = (0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75)
CHUNK_SIZES = (800, 1_200, 1_600)
CHUNK_OVERLAP = 200
HARD_NEGATIVES_PER_QUERY = 10


class QualityEvaluationError(RuntimeError):
    """Raised when the quality experiment cannot produce a trusted report."""


@dataclass(frozen=True)
class QualityCase:
    case_id: str
    query: str
    expected_decision_id: str | None
    expected_decision_type: str | None = None
    expected_chamber: str | None = None

    @property
    def is_relevant(self) -> bool:
        return self.expected_decision_id is not None


EVALUATION_CASES = (
    QualityCase(
        "gecersiz_fesih_ise_iade",
        (
            "İşveren belirsiz süreli iş sözleşmemi geçerli bir neden göstermeden "
            "feshetti. İşe iade ve işe başlatmama tazminatı talep edebilir miyim?"
        ),
        "d1113966700",
        "hukuk",
        "7. Hukuk Dairesi",
    ),
    QualityCase(
        "tapu_iptali_tescil",
        (
            "Belediyeden bedelini ödeyerek satın aldığım taşınmaz payının tapusu "
            "verilmedi. Tapu kaydının iptali ve adıma tescilini istiyorum."
        ),
        "d581878400",
        "hukuk",
        "14. Hukuk Dairesi",
    ),
    QualityCase(
        "uyusturucu_ticareti",
        (
            "Uyuşturucu madde ticareti suçunda tanık dinlenmeden ve eksik "
            "soruşturmayla mahkûmiyet kararı verilmiş. Temyizde nasıl değerlendirilir?"
        ),
        "d480864200",
        "ceza",
        "9. Ceza Dairesi",
    ),
    QualityCase(
        "vergi_tarhiyati",
        (
            "Şirket adına düzenlenen vergi inceleme raporuna dayanılarak kurumlar "
            "vergisi tarh edildi ve vergi ziyaı cezası kesildi. Vergi mahkemesinde "
            "tarhiyatın iptalini istiyorum."
        ),
        None,
    ),
    QualityCase(
        "memur_atama_islemi",
        (
            "Kamu kurumundaki memur kadrosuna atanma talebim idari işlemle "
            "reddedildi. Atama işleminin iptali ve yürütmenin durdurulması için "
            "idare mahkemesine başvurmak istiyorum."
        ),
        None,
    ),
    QualityCase(
        "imar_plani_iptali",
        (
            "Belediyenin yeni imar planı taşınmazımı park alanına ayırdı. Askı "
            "süresinde itiraz ettim; plan değişikliğinin kamu yararına aykırı olduğu "
            "gerekçesiyle iptal davası açmak istiyorum."
        ),
        None,
    ),
)


class EmbeddingClientProtocol(Protocol):
    model: str
    base_url: str

    def ensure_model_available(self) -> tuple[str, ...]: ...

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]: ...


class VectorStoreProtocol(Protocol):
    collection_name: str

    def ensure_collection(self) -> Mapping[str, Any]: ...

    def count(self) -> int: ...

    def search(
        self,
        query_vector: Sequence[float],
        *,
        limit: int,
        metadata_filters: Mapping[str, str | bool] | None = None,
        score_threshold: float | None = None,
    ) -> tuple[SearchHit, ...]: ...


def decision_rankings(hits: Sequence[SearchHit], *, limit: int = 20) -> list[dict[str, Any]]:
    """Collapse duplicate chunks into first-seen, decision-level rankings."""
    rankings: list[dict[str, Any]] = []
    seen: set[str] = set()
    for hit in hits:
        decision_id = hit.payload.get("karar_id")
        if not isinstance(decision_id, str) or not decision_id:
            raise QualityEvaluationError("Search hit has no valid karar_id")
        if decision_id in seen:
            continue
        rankings.append(
            {
                "karar_id": decision_id,
                "chunk_id": hit.chunk_id,
                "score": round(float(hit.score), 6),
                "daire": hit.payload.get("daire"),
                "karar_turu": hit.payload.get("karar_turu"),
            }
        )
        seen.add(decision_id)
        if len(rankings) == limit:
            break
    return rankings


def evaluate_configuration(
    cases: Sequence[QualityCase],
    rankings_by_case: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    top_k: int,
    threshold: float | None,
) -> dict[str, Any]:
    """Measure relevant recall and out-of-domain rejection for one setting."""
    relevant_hits = 0
    reciprocal_ranks: list[float] = []
    out_of_domain_rejections = 0
    relevant_count = sum(case.is_relevant for case in cases)
    out_of_domain_count = len(cases) - relevant_count
    case_results: list[dict[str, Any]] = []

    for case in cases:
        rankings = list(rankings_by_case[case.case_id])[:top_k]
        retained = [
            result
            for result in rankings
            if threshold is None or float(result["score"]) >= threshold
        ]
        if case.is_relevant:
            rank = next(
                (
                    index
                    for index, result in enumerate(retained, start=1)
                    if result["karar_id"] == case.expected_decision_id
                ),
                None,
            )
            hit = rank is not None
            relevant_hits += int(hit)
            reciprocal_ranks.append(0.0 if rank is None else 1.0 / rank)
            case_results.append(
                {
                    "case_id": case.case_id,
                    "beklenen_karar_id": case.expected_decision_id,
                    "bulundu": hit,
                    "sira": rank,
                    "esik_ustu_sonuc_sayisi": len(retained),
                }
            )
        else:
            rejected = not retained
            out_of_domain_rejections += int(rejected)
            case_results.append(
                {
                    "case_id": case.case_id,
                    "alan_disi_reddedildi": rejected,
                    "esik_ustu_sonuc_sayisi": len(retained),
                    "en_yuksek_skor": rankings[0]["score"] if rankings else None,
                }
            )

    recall = relevant_hits / relevant_count if relevant_count else 0.0
    rejection = (
        out_of_domain_rejections / out_of_domain_count
        if out_of_domain_count
        else 0.0
    )
    return {
        "top_k": top_k,
        "minimum_score": threshold,
        "ilgili_bulunan": relevant_hits,
        "ilgili_sorgu_sayisi": relevant_count,
        "ilgili_recall": round(recall, 6),
        "mrr": round(statistics.fmean(reciprocal_ranks), 6),
        "alan_disi_reddedilen": out_of_domain_rejections,
        "alan_disi_sorgu_sayisi": out_of_domain_count,
        "alan_disi_reddetme_orani": round(rejection, 6),
        "dengeli_dogruluk": round((recall + rejection) / 2, 6),
        "cases": case_results,
    }


def choose_recommended_configuration(
    comparisons: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Choose the safest high-recall setting deterministically."""
    if not comparisons:
        raise QualityEvaluationError("Threshold comparison is empty")
    best = max(
        comparisons,
        key=lambda row: (
            float(row["dengeli_dogruluk"]),
            float(row["ilgili_recall"]),
            float(row["alan_disi_reddetme_orani"]),
            -int(row["top_k"]),
            float(row["minimum_score"]),
        ),
    )
    return {
        "top_k": best["top_k"],
        "minimum_score": best["minimum_score"],
        "ilgili_recall": best["ilgili_recall"],
        "alan_disi_reddetme_orani": best["alan_disi_reddetme_orani"],
        "dengeli_dogruluk": best["dengeli_dogruluk"],
        "not": (
            "Bu değerler altı sorguluk geliştirme deneyi içindir; üretim varsayılanı "
            "olarak sabitlenmeden önce daha geniş etiketli veriyle doğrulanmalıdır."
        ),
    }


def _batch_embed(
    client: EmbeddingClientProtocol,
    texts: Sequence[str],
    *,
    batch_size: int,
) -> list[list[float]]:
    vectors: list[list[float]] = []
    for start in range(0, len(texts), batch_size):
        vectors.extend(client.embed_texts(texts[start : start + batch_size]))
    if len(vectors) != len(texts):
        raise QualityEvaluationError("Embedding count mismatch")
    return vectors


def _filtered_rankings(
    store: VectorStoreProtocol,
    cases: Sequence[QualityCase],
    query_vectors: Mapping[str, Sequence[float]],
) -> dict[str, Any]:
    relevant_cases = [case for case in cases if case.is_relevant]
    modes: dict[str, dict[str, list[dict[str, Any]]]] = {
        "filtresiz": {},
        "karar_turu": {},
        "daire": {},
    }
    for case in relevant_cases:
        vector = query_vectors[case.case_id]
        for mode, metadata_filters in (
            ("filtresiz", None),
            ("karar_turu", {"karar_turu": case.expected_decision_type}),
            ("daire", {"daire": case.expected_chamber}),
        ):
            if mode == "filtresiz":
                continue
            hits = store.search(
                vector,
                limit=SEARCH_CANDIDATE_LIMIT,
                metadata_filters=metadata_filters,
            )
            modes[mode][case.case_id] = decision_rankings(hits)
    return modes


def _compare_filters(
    cases: Sequence[QualityCase],
    baseline: Mapping[str, Sequence[Mapping[str, Any]]],
    filtered: dict[str, dict[str, list[dict[str, Any]]]],
) -> list[dict[str, Any]]:
    relevant_cases = tuple(case for case in cases if case.is_relevant)
    filtered["filtresiz"] = {
        case.case_id: list(baseline[case.case_id]) for case in relevant_cases
    }
    rows: list[dict[str, Any]] = []
    for mode in ("filtresiz", "karar_turu", "daire"):
        metrics = evaluate_configuration(
            relevant_cases,
            filtered[mode],
            top_k=5,
            threshold=None,
        )
        rows.append(
            {
                "filtre_modu": mode,
                "top_k": 5,
                "ilgili_recall": metrics["ilgili_recall"],
                "mrr": metrics["mrr"],
                "cases": metrics["cases"],
            }
        )
    return rows


def _load_selected_decisions(
    path: Path,
    decision_ids: set[str],
) -> dict[str, dict[str, Any]]:
    records = load_cleaned_records(path, expected_count=DEFAULT_EXPECTED_DECISIONS)
    selected = {record["id"]: record for record in records if record["id"] in decision_ids}
    missing = decision_ids - set(selected)
    if missing:
        raise QualityEvaluationError(
            "Clean corpus is missing candidate decisions: " + ", ".join(sorted(missing))
        )
    return selected


def _compare_chunk_sizes(
    cases: Sequence[QualityCase],
    baseline: Mapping[str, Sequence[Mapping[str, Any]]],
    query_vectors: Mapping[str, Sequence[float]],
    *,
    clean_data_path: Path,
    embedding_client: EmbeddingClientProtocol,
    batch_size: int,
) -> dict[str, Any]:
    relevant_cases = tuple(case for case in cases if case.is_relevant)
    candidate_ids = {
        str(case.expected_decision_id) for case in relevant_cases
    }
    for case in relevant_cases:
        candidate_ids.update(
            str(item["karar_id"])
            for item in baseline[case.case_id][:HARD_NEGATIVES_PER_QUERY]
        )
    decisions = _load_selected_decisions(clean_data_path, candidate_ids)
    results: list[dict[str, Any]] = []

    for chunk_size in CHUNK_SIZES:
        chunks: list[dict[str, Any]] = []
        for decision_id in sorted(decisions):
            chunks.extend(
                chunk_decision_record(
                    decisions[decision_id],
                    chunk_size=chunk_size,
                    overlap=CHUNK_OVERLAP,
                )
            )
        chunk_vectors = _batch_embed(
            embedding_client,
            [chunk["chunk_metni"] for chunk in chunks],
            batch_size=batch_size,
        )
        rankings_by_case: dict[str, list[dict[str, Any]]] = {}
        for case in relevant_cases:
            best_by_decision: dict[str, tuple[float, str]] = {}
            for chunk, vector in zip(chunks, chunk_vectors):
                score = cosine_similarity(query_vectors[case.case_id], vector)
                decision_id = chunk["karar_id"]
                current = best_by_decision.get(decision_id)
                if current is None or score > current[0]:
                    best_by_decision[decision_id] = (score, chunk["id"])
            rankings_by_case[case.case_id] = [
                {
                    "karar_id": decision_id,
                    "chunk_id": values[1],
                    "score": round(values[0], 6),
                }
                for decision_id, values in sorted(
                    best_by_decision.items(), key=lambda item: item[1][0], reverse=True
                )
            ]
        metrics = evaluate_configuration(
            relevant_cases,
            rankings_by_case,
            top_k=5,
            threshold=None,
        )
        results.append(
            {
                "chunk_size": chunk_size,
                "overlap": CHUNK_OVERLAP,
                "aday_karar_sayisi": len(decisions),
                "chunk_sayisi": len(chunks),
                "recall_at_5": metrics["ilgili_recall"],
                "mrr": metrics["mrr"],
                "cases": metrics["cases"],
            }
        )
    best = max(
        results,
        key=lambda row: (
            float(row["recall_at_5"]),
            float(row["mrr"]),
            -abs(int(row["chunk_size"]) - 1_200),
        ),
    )
    return {
        "yontem": (
            "Tam indeksin ilk 10 sonuçlarından türetilen gerçek zor negatif kararlar "
            "üzerinde, karar başına en yüksek chunk skoru karşılaştırıldı."
        ),
        "results": results,
        "onerilen_chunk_size": best["chunk_size"],
        "onerilen_overlap": best["overlap"],
    }


def _atomic_write_json(path: Path, report: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        temporary_path.replace(path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def run_evaluation(
    *,
    clean_data_path: Path = DEFAULT_CLEAN_DATA,
    qdrant_path: Path = DEFAULT_QDRANT_PATH,
    output_path: Path = DEFAULT_OUTPUT,
    collection_name: str = DEFAULT_COLLECTION_NAME,
    expected_points: int = DEFAULT_EXPECTED_POINTS,
    embedding_client: EmbeddingClientProtocol | None = None,
    vector_store: VectorStoreProtocol | None = None,
    batch_size: int = 64,
) -> dict[str, Any]:
    """Run the live full-index and controlled chunk-size comparisons."""
    started = time.perf_counter()
    client = embedding_client or LMStudioEmbeddingClient(
        base_url=DEFAULT_BASE_URL,
        model=DEFAULT_EMBEDDING_MODEL,
    )
    client.ensure_model_available()
    owned_store = vector_store is None
    store = vector_store or QdrantVectorStore(
        path=qdrant_path,
        collection_name=collection_name,
        vector_size=DEFAULT_VECTOR_SIZE,
        embedding_model=client.model,
    )
    try:
        schema = dict(store.ensure_collection())
        point_count = store.count()
        if point_count != expected_points:
            raise QualityEvaluationError(
                f"Qdrant point count mismatch: expected {expected_points}, got {point_count}"
            )

        vectors = client.embed_texts([case.query for case in EVALUATION_CASES])
        query_vectors = {
            case.case_id: vector for case, vector in zip(EVALUATION_CASES, vectors)
        }
        baseline: dict[str, list[dict[str, Any]]] = {}
        for case in EVALUATION_CASES:
            hits = store.search(
                query_vectors[case.case_id],
                limit=SEARCH_CANDIDATE_LIMIT,
            )
            baseline[case.case_id] = decision_rankings(hits)

        top_k_comparison = [
            evaluate_configuration(
                EVALUATION_CASES,
                baseline,
                top_k=top_k,
                threshold=None,
            )
            for top_k in TOP_K_VALUES
        ]
        threshold_comparison = [
            evaluate_configuration(
                EVALUATION_CASES,
                baseline,
                top_k=top_k,
                threshold=threshold,
            )
            for top_k in TOP_K_VALUES
            for threshold in THRESHOLD_VALUES
        ]
        filtered = _filtered_rankings(
            store, EVALUATION_CASES, query_vectors
        )
        filter_comparison = _compare_filters(
            EVALUATION_CASES, baseline, filtered
        )
        chunk_comparison = _compare_chunk_sizes(
            EVALUATION_CASES,
            baseline,
            query_vectors,
            clean_data_path=clean_data_path,
            embedding_client=client,
            batch_size=batch_size,
        )
        recommendation = choose_recommended_configuration(threshold_comparison)

        report = {
            "evaluation_version": EVALUATION_VERSION,
            "embedding_model": client.model,
            "embedding_base_url": client.base_url,
            "qdrant": {
                "path": str(qdrant_path),
                "collection": store.collection_name,
                "point_count": point_count,
                "schema": schema,
            },
            "cases": [asdict(case) for case in EVALUATION_CASES],
            "decision_level_baseline": baseline,
            "top_k_comparison": top_k_comparison,
            "threshold_comparison": threshold_comparison,
            "filter_comparison": filter_comparison,
            "chunk_size_comparison": chunk_comparison,
            "recommendation": recommendation,
            "limitations": [
                "Üç ilgili ve üç alan dışı sorgu üretim doğruluğunu temsil etmez.",
                "Chunk boyutu deneyi tam corpus yerine gerçek zor negatif aday havuzunu kullanır.",
                "Daire filtresi yalnızca kullanıcı daireyi önceden güvenle biliyorsa uygulanmalıdır.",
            ],
            "duration_seconds": round(time.perf_counter() - started, 3),
        }
        _atomic_write_json(output_path, report)
        return report
    finally:
        if owned_store and isinstance(store, QdrantVectorStore):
            store.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare Day 17 semantic-search quality settings."
    )
    parser.add_argument("--clean-data", type=Path, default=DEFAULT_CLEAN_DATA)
    parser.add_argument("--qdrant-path", type=Path, default=DEFAULT_QDRANT_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--collection", default=DEFAULT_COLLECTION_NAME)
    parser.add_argument("--expected-points", type=int, default=DEFAULT_EXPECTED_POINTS)
    parser.add_argument("--batch-size", type=int, default=64)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.batch_size < 1:
        raise SystemExit("--batch-size must be positive")
    report = run_evaluation(
        clean_data_path=args.clean_data,
        qdrant_path=args.qdrant_path,
        output_path=args.output,
        collection_name=args.collection,
        expected_points=args.expected_points,
        batch_size=args.batch_size,
    )
    recommendation = report["recommendation"]
    print(f"Quality report: {args.output}")
    print(f"Qdrant points: {report['qdrant']['point_count']}")
    print(
        "Recommended experiment setting: "
        f"top_k={recommendation['top_k']}, "
        f"min_score={recommendation['minimum_score']}, "
        f"balanced_accuracy={recommendation['dengeli_dogruluk']}"
    )
    print(
        "Recommended chunking: "
        f"{report['chunk_size_comparison']['onerilen_chunk_size']}/"
        f"{report['chunk_size_comparison']['onerilen_overlap']}"
    )


if __name__ == "__main__":
    main()
