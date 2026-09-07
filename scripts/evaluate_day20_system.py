"""Evaluate Day 20 retrieval, chunking, RAG quality, and performance."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import statistics
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.rag_answer import (  # noqa: E402
    DEFAULT_RAG_MIN_SCORE,
    DEFAULT_RAG_TOP_K,
    MINIMUM_RAG_SOURCES,
    PROMPT_VERSION,
    RAGAnswerError,
    RAGAnswerService,
    quality_limit_is_disclosed,
)
from app.semantic_search import SemanticSearchService, normalize_query  # noqa: E402
from scripts.chunk_yargitay_data import (  # noqa: E402
    chunk_decision_record,
    load_cleaned_records,
)
from scripts.lmstudio_chat import (  # noqa: E402
    DEFAULT_CHAT_MODEL,
    LMStudioChatClient,
)
from scripts.lmstudio_embeddings import (  # noqa: E402
    DEFAULT_BASE_URL,
    DEFAULT_EMBEDDING_MODEL,
    LMStudioEmbeddingClient,
    cosine_similarity,
)
from scripts.qdrant_vector_store import (  # noqa: E402
    DEFAULT_COLLECTION_NAME,
    DEFAULT_VECTOR_SIZE,
    QdrantVectorStore,
    SearchHit,
)


EVALUATION_VERSION = "1.0"
DEFAULT_CASES_PATH = Path("data/evaluation/day20_cases.json")
DEFAULT_CLEAN_DATA = Path("data/processed/yargitay_clean_14870.jsonl")
DEFAULT_QDRANT_PATH = Path("data/vector_store/qdrant")
DEFAULT_OUTPUT = Path("data/processed/yargitay_day20_evaluation.json")
DEFAULT_EXPECTED_DECISIONS = 14_870
DEFAULT_EXPECTED_POINTS = 31_544
SEARCH_LIMIT = 100
TOP_K_VALUES = (3, 5, 10, 20)
THRESHOLD_VALUES = (0.55, 0.60, 0.62, 0.65, 0.68, 0.70, 0.75)
CHUNK_CONFIGURATIONS = ((800, 100), (800, 200), (1_200, 200), (1_600, 200))
HARD_NEGATIVES_PER_CASE = 10
LEGAL_CLOSING = (
    "Somut olayın özelliklerine göre sonuç değişebilir; bu değerlendirme "
    "hukuki danışmanlık değildir."
)


class Day20EvaluationError(RuntimeError):
    """Raised when the Day 20 report cannot be trusted."""


@dataclass(frozen=True)
class EvaluationCase:
    case_id: str
    hukuk_alani: str
    query: str
    expected_decision_ids: tuple[str, ...]
    expected_chamber: str | None
    rag_test: bool

    @property
    def is_in_domain(self) -> bool:
        return bool(self.expected_decision_ids)


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


def _required_text(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise Day20EvaluationError(f"{name} boş veya metin değil")
    return value.strip()


def load_evaluation_cases(
    path: Path,
) -> tuple[str, str, tuple[EvaluationCase, ...]]:
    """Load and strictly validate the committed Day 20 test set."""
    try:
        raw_bytes = path.read_bytes()
    except OSError as exc:
        raise Day20EvaluationError(f"Test seti okunamadı: {path}: {exc}") from exc
    try:
        payload = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Day20EvaluationError("Test seti geçerli UTF-8 JSON değil") from exc
    if not isinstance(payload, dict):
        raise Day20EvaluationError("Test seti kökü nesne olmalıdır")
    version = _required_text(payload.get("version"), name="version")
    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise Day20EvaluationError("Test seti boş veya liste değil")

    cases: list[EvaluationCase] = []
    seen_ids: set[str] = set()
    for index, raw_case in enumerate(raw_cases):
        if not isinstance(raw_case, dict):
            raise Day20EvaluationError(f"Test olayı {index} nesne değil")
        allowed = {
            "case_id",
            "hukuk_alani",
            "query",
            "expected_decision_ids",
            "expected_chamber",
            "rag_test",
        }
        unknown = set(raw_case) - allowed
        if unknown:
            raise Day20EvaluationError(
                f"Test olayı {index} bilinmeyen alan içeriyor: {sorted(unknown)}"
            )
        case_id = _required_text(raw_case.get("case_id"), name="case_id")
        if case_id in seen_ids:
            raise Day20EvaluationError(f"Tekrarlanan case_id: {case_id}")
        seen_ids.add(case_id)
        query = normalize_query(raw_case.get("query"))
        raw_expected = raw_case.get("expected_decision_ids")
        if not isinstance(raw_expected, list) or not all(
            isinstance(item, str) and item.strip() for item in raw_expected
        ):
            raise Day20EvaluationError(
                f"{case_id} expected_decision_ids geçerli bir liste değil"
            )
        expected = tuple(item.strip() for item in raw_expected)
        if len(expected) != len(set(expected)):
            raise Day20EvaluationError(f"{case_id} tekrarlanan çapa karar içeriyor")
        chamber = raw_case.get("expected_chamber")
        if chamber is not None:
            chamber = _required_text(chamber, name=f"{case_id}.expected_chamber")
        rag_test = raw_case.get("rag_test")
        if not isinstance(rag_test, bool):
            raise Day20EvaluationError(f"{case_id}.rag_test boolean olmalıdır")
        if bool(expected) != bool(chamber):
            raise Day20EvaluationError(
                f"{case_id} çapa karar ve daire alanları birlikte verilmelidir"
            )
        if rag_test and not expected:
            raise Day20EvaluationError(
                f"{case_id} alan dışı olduğu için RAG testi olamaz"
            )
        cases.append(
            EvaluationCase(
                case_id=case_id,
                hukuk_alani=_required_text(
                    raw_case.get("hukuk_alani"), name=f"{case_id}.hukuk_alani"
                ),
                query=query,
                expected_decision_ids=expected,
                expected_chamber=chamber,
                rag_test=rag_test,
            )
        )

    if len(cases) < 10:
        raise Day20EvaluationError("Test seti en az 10 olay içermelidir")
    if not any(case.is_in_domain for case in cases):
        raise Day20EvaluationError("Test setinde Yargıtay kapsamı olayı yok")
    if all(case.is_in_domain for case in cases):
        raise Day20EvaluationError("Test setinde alan dışı kontrol olayı yok")
    return version, hashlib.sha256(raw_bytes).hexdigest(), tuple(cases)


def decision_rankings(
    hits: Sequence[SearchHit], *, limit: int = SEARCH_LIMIT
) -> list[dict[str, Any]]:
    """Collapse chunk hits into stable decision-level rankings."""
    rankings: list[dict[str, Any]] = []
    seen: set[str] = set()
    for hit in hits:
        decision_id = hit.payload.get("karar_id")
        if not isinstance(decision_id, str) or not decision_id.strip():
            raise Day20EvaluationError("Arama sonucu geçerli karar_id içermiyor")
        if decision_id in seen:
            continue
        score = float(hit.score)
        if not math.isfinite(score):
            raise Day20EvaluationError("Arama sonucu sonlu olmayan skor içeriyor")
        rankings.append(
            {
                "karar_id": decision_id,
                "chunk_id": hit.chunk_id,
                "score": round(score, 6),
                "daire": hit.payload.get("daire"),
                "karar_turu": hit.payload.get("karar_turu"),
            }
        )
        seen.add(decision_id)
        if len(rankings) == limit:
            break
    return rankings


def evaluate_configuration(
    cases: Sequence[EvaluationCase],
    rankings_by_case: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    top_k: int,
    threshold: float,
) -> dict[str, Any]:
    """Measure anchor recall and RAG-safe out-of-domain rejection."""
    in_domain_count = sum(case.is_in_domain for case in cases)
    out_of_domain_count = len(cases) - in_domain_count
    anchors_found = 0
    out_of_domain_rejected = 0
    out_of_domain_zero_results = 0
    reciprocal_ranks: list[float] = []
    case_results: list[dict[str, Any]] = []

    for case in cases:
        rankings = list(rankings_by_case[case.case_id])[:top_k]
        retained = [row for row in rankings if float(row["score"]) >= threshold]
        if case.is_in_domain:
            expected = set(case.expected_decision_ids)
            rank = next(
                (
                    index
                    for index, row in enumerate(retained, start=1)
                    if row["karar_id"] in expected
                ),
                None,
            )
            found = rank is not None
            anchors_found += int(found)
            reciprocal_ranks.append(0.0 if rank is None else 1.0 / rank)
            case_results.append(
                {
                    "case_id": case.case_id,
                    "capa_bulundu": found,
                    "capa_sirasi": rank,
                    "esik_ustu_sonuc_sayisi": len(retained),
                }
            )
        else:
            zero_results = not retained
            rejected = len(retained) < MINIMUM_RAG_SOURCES
            out_of_domain_rejected += int(rejected)
            out_of_domain_zero_results += int(zero_results)
            case_results.append(
                {
                    "case_id": case.case_id,
                    "alan_disi_reddedildi": rejected,
                    "sifir_sonuc": zero_results,
                    "esik_ustu_sonuc_sayisi": len(retained),
                    "en_yuksek_skor": rankings[0]["score"] if rankings else None,
                }
            )

    anchor_recall = anchors_found / in_domain_count if in_domain_count else 0.0
    rejection_rate = (
        out_of_domain_rejected / out_of_domain_count if out_of_domain_count else 0.0
    )
    zero_result_rate = (
        out_of_domain_zero_results / out_of_domain_count
        if out_of_domain_count
        else 0.0
    )
    return {
        "top_k": top_k,
        "minimum_score": threshold,
        "capa_bulunan": anchors_found,
        "capa_sorgu_sayisi": in_domain_count,
        "capa_recall": round(anchor_recall, 6),
        "mrr": round(statistics.fmean(reciprocal_ranks), 6),
        "alan_disi_reddedilen": out_of_domain_rejected,
        "alan_disi_sorgu_sayisi": out_of_domain_count,
        "alan_disi_reddetme_orani": round(rejection_rate, 6),
        "alan_disi_sifir_sonuc_orani": round(zero_result_rate, 6),
        "dengeli_dogruluk": round((anchor_recall + rejection_rate) / 2, 6),
        "cases": case_results,
    }


def choose_recommended_configuration(
    comparisons: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Choose a deterministic balance, preferring recall on exact ties."""
    if not comparisons:
        raise Day20EvaluationError("Yapılandırma karşılaştırması boş")
    best = max(
        comparisons,
        key=lambda row: (
            float(row["dengeli_dogruluk"]),
            float(row["capa_recall"]),
            float(row["alan_disi_reddetme_orani"]),
            float(row["mrr"]),
            -int(row["top_k"]),
            float(row["minimum_score"]),
        ),
    )
    return {
        key: best[key]
        for key in (
            "top_k",
            "minimum_score",
            "capa_recall",
            "mrr",
            "alan_disi_reddetme_orani",
            "alan_disi_sifir_sonuc_orani",
            "dengeli_dogruluk",
        )
    }


def analyze_retrieval_errors(
    cases: Sequence[EvaluationCase],
    rankings_by_case: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    top_k: int,
    threshold: float,
) -> list[dict[str, Any]]:
    """Explain misses and false acceptances using observable ranks and scores."""
    analyses: list[dict[str, Any]] = []
    for case in cases:
        rankings = list(rankings_by_case[case.case_id])
        if case.is_in_domain:
            expected = set(case.expected_decision_ids)
            expected_position = next(
                (
                    index
                    for index, row in enumerate(rankings, start=1)
                    if row["karar_id"] in expected
                ),
                None,
            )
            expected_score = (
                None
                if expected_position is None
                else rankings[expected_position - 1]["score"]
            )
            retained = (
                expected_position is not None
                and expected_position <= top_k
                and float(expected_score) >= threshold
            )
            if retained:
                reason = "çapa karar önerilen ayarda bulundu"
            elif expected_position is None:
                reason = "çapa karar ilk 100 chunk adayından oluşan karar havuzuna girmedi"
            elif expected_position > top_k:
                reason = "çapa kararın sırası top_k sınırının dışında kaldı"
            else:
                reason = "çapa kararın skoru benzerlik eşiğinin altında kaldı"
            analyses.append(
                {
                    "case_id": case.case_id,
                    "hukuk_alani": case.hukuk_alani,
                    "tur": "capa_karar",
                    "basarili": retained,
                    "capa_sirasi": expected_position,
                    "capa_skoru": expected_score,
                    "en_ust_karar_id": rankings[0]["karar_id"] if rankings else None,
                    "en_ust_skor": rankings[0]["score"] if rankings else None,
                    "neden": reason,
                }
            )
        else:
            retained = [
                row
                for row in rankings[:top_k]
                if float(row["score"]) >= threshold
            ]
            rejected = len(retained) < MINIMUM_RAG_SOURCES
            analyses.append(
                {
                    "case_id": case.case_id,
                    "hukuk_alani": case.hukuk_alani,
                    "tur": "alan_disi",
                    "basarili": rejected,
                    "esik_ustu_sonuc_sayisi": len(retained),
                    "en_ust_karar_id": rankings[0]["karar_id"] if rankings else None,
                    "en_ust_skor": rankings[0]["score"] if rankings else None,
                    "neden": (
                        "alan dışı sorgu iki kaynak güvenlik sınırının altında kaldı"
                        if rejected
                        else "sözcüksel veya anlamsal benzerlik alan dışı sorguyu eşik üstünde tuttu"
                    ),
                }
            )
    return analyses


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
        raise Day20EvaluationError("Embedding sayısı girdi sayısıyla eşleşmiyor")
    return vectors


def _load_candidate_decisions(
    path: Path,
    decision_ids: set[str],
) -> dict[str, dict[str, Any]]:
    records = load_cleaned_records(path, expected_count=DEFAULT_EXPECTED_DECISIONS)
    selected = {record["id"]: record for record in records if record["id"] in decision_ids}
    missing = decision_ids - set(selected)
    if missing:
        raise Day20EvaluationError(
            "Temiz corpusta aday kararlar eksik: " + ", ".join(sorted(missing))
        )
    return selected


def compare_chunk_configurations(
    cases: Sequence[EvaluationCase],
    rankings_by_case: Mapping[str, Sequence[Mapping[str, Any]]],
    query_vectors: Mapping[str, Sequence[float]],
    *,
    clean_data_path: Path,
    embedding_client: EmbeddingClientProtocol,
    batch_size: int,
) -> dict[str, Any]:
    """Compare chunk settings on a pooled, real hard-negative decision set."""
    in_domain_cases = tuple(case for case in cases if case.is_in_domain)
    candidate_ids = {
        decision_id
        for case in in_domain_cases
        for decision_id in case.expected_decision_ids
    }
    for case in in_domain_cases:
        candidate_ids.update(
            str(row["karar_id"])
            for row in rankings_by_case[case.case_id][
                :HARD_NEGATIVES_PER_CASE
            ]
        )
    decisions = _load_candidate_decisions(clean_data_path, candidate_ids)
    rows: list[dict[str, Any]] = []

    for chunk_size, overlap in CHUNK_CONFIGURATIONS:
        chunks: list[dict[str, Any]] = []
        for decision_id in sorted(decisions):
            chunks.extend(
                chunk_decision_record(
                    decisions[decision_id],
                    chunk_size=chunk_size,
                    overlap=overlap,
                )
            )
        started = time.perf_counter()
        chunk_vectors = _batch_embed(
            embedding_client,
            [chunk["chunk_metni"] for chunk in chunks],
            batch_size=batch_size,
        )
        embedding_ms = round((time.perf_counter() - started) * 1_000, 3)
        rankings: dict[str, list[dict[str, Any]]] = {}
        for case in in_domain_cases:
            best_by_decision: dict[str, tuple[float, str]] = {}
            for chunk, vector in zip(chunks, chunk_vectors):
                score = cosine_similarity(query_vectors[case.case_id], vector)
                decision_id = chunk["karar_id"]
                current = best_by_decision.get(decision_id)
                if current is None or score > current[0]:
                    best_by_decision[decision_id] = (score, chunk["id"])
            rankings[case.case_id] = [
                {
                    "karar_id": decision_id,
                    "chunk_id": score_and_chunk[1],
                    "score": round(score_and_chunk[0], 6),
                }
                for decision_id, score_and_chunk in sorted(
                    best_by_decision.items(),
                    key=lambda item: item[1][0],
                    reverse=True,
                )
            ]
        recall_at_5 = evaluate_configuration(
            in_domain_cases,
            rankings,
            top_k=5,
            threshold=-1.0,
        )
        recall_at_10 = evaluate_configuration(
            in_domain_cases,
            rankings,
            top_k=10,
            threshold=-1.0,
        )
        rows.append(
            {
                "chunk_size": chunk_size,
                "overlap": overlap,
                "aday_karar_sayisi": len(decisions),
                "chunk_sayisi": len(chunks),
                "ortalama_chunk_karakteri": round(
                    statistics.fmean(len(chunk["chunk_metni"]) for chunk in chunks),
                    3,
                ),
                "embedding_ms": embedding_ms,
                "recall_at_5": recall_at_5["capa_recall"],
                "mrr_at_5": recall_at_5["mrr"],
                "recall_at_10": recall_at_10["capa_recall"],
                "mrr_at_10": recall_at_10["mrr"],
                "cases_at_10": recall_at_10["cases"],
            }
        )
    best = max(
        rows,
        key=lambda row: (
            float(row["recall_at_10"]),
            float(row["mrr_at_10"]),
            -int(row["chunk_sayisi"]),
            -abs(int(row["chunk_size"]) - 1_200),
        ),
    )
    return {
        "yontem": (
            "On çapa sorgunun tam indeks ilk 10 sonuçları ve etiketli çapa "
            "kararlarından oluşturulan havuzda karar başına en yüksek chunk skoru."
        ),
        "results": rows,
        "onerilen_chunk_size": best["chunk_size"],
        "onerilen_overlap": best["overlap"],
    }


def _percentile(values: Sequence[float], fraction: float) -> float:
    if not values:
        raise Day20EvaluationError("Yüzdelik için ölçüm yok")
    ordered = sorted(values)
    index = max(0, math.ceil(fraction * len(ordered)) - 1)
    return round(ordered[index], 3)


def evaluate_rag_cases(
    cases: Sequence[EvaluationCase],
    service: RAGAnswerService,
    *,
    top_k: int,
    min_score: float,
) -> dict[str, Any]:
    """Run selected multi-domain cases through retrieval and real Gemma."""
    selected = tuple(case for case in cases if case.rag_test)
    rows: list[dict[str, Any]] = []
    for case in selected:
        started = time.perf_counter()
        try:
            response = service.answer(
                case.query,
                top_k=top_k,
                min_score=min_score,
            )
        except RAGAnswerError as exc:
            rows.append(
                {
                    "case_id": case.case_id,
                    "hukuk_alani": case.hukuk_alani,
                    "durum": "hata",
                    "hata": str(exc),
                    "sure_ms": round((time.perf_counter() - started) * 1_000, 3),
                }
            )
            continue
        sources = response["kaynaklar"]
        source_ids = {source["karar_id"] for source in sources}
        answer = response["cevap"]
        stats = response["model_istatistikleri"] or {}
        quality_warning_required = any(
            source["veri_kalite_uyarilari"] for source in sources
        )
        rows.append(
            {
                "case_id": case.case_id,
                "hukuk_alani": case.hukuk_alani,
                "durum": response["durum"],
                "llm_cagrildi": response["llm_cagrildi"],
                "bulunan_kaynak_sayisi": response["bulunan_kaynak_sayisi"],
                "kullanilan_kaynak_sayisi": response["kullanilan_kaynak_sayisi"],
                "capa_kaynaklarda": bool(
                    source_ids.intersection(case.expected_decision_ids)
                ),
                "kalite_uyarili_kaynak_sayisi": sum(
                    bool(source["veri_kalite_uyarilari"]) for source in sources
                ),
                "kalite_uyarisi_aciklandi": (
                    quality_limit_is_disclosed(answer)
                    if quality_warning_required
                    else None
                ),
                "kaynak_etiketi_var": "[K" in answer,
                "zorunlu_uyari_var": answer.endswith(LEGAL_CLOSING),
                "reasoning_tokens": stats.get("reasoning_output_tokens"),
                "model_cagri_sayisi": response["model_cagri_sayisi"],
                "input_tokens": stats.get("input_tokens"),
                "output_tokens": stats.get("total_output_tokens"),
                "sure_ms": response["sure_ms"],
                "olculen_duvar_suresi_ms": round(
                    (time.perf_counter() - started) * 1_000, 3
                ),
                "cevap": answer,
            }
        )
    completed = [row for row in rows if row["durum"] == "tamamlandi"]
    failures = [row for row in rows if row["durum"] == "hata"]
    timings = [float(row["sure_ms"]) for row in rows if "sure_ms" in row]
    quality_warning_rows = [
        row for row in rows if row.get("kalite_uyarisi_aciklandi") is not None
    ]
    return {
        "top_k": top_k,
        "minimum_score": min_score,
        "prompt_version": PROMPT_VERSION,
        "case_count": len(selected),
        "completed_count": len(completed),
        "safe_insufficient_count": sum(
            row["durum"] == "yetersiz_kaynak" for row in rows
        ),
        "failure_count": len(failures),
        "total_model_call_count": sum(
            int(row.get("model_cagri_sayisi", 0)) for row in rows
        ),
        "retry_case_count": sum(
            int(row.get("model_cagri_sayisi", 0)) > 1 for row in rows
        ),
        "citation_validation_rate": round(
            sum(row.get("kaynak_etiketi_var") is True for row in rows) / len(rows),
            6,
        ),
        "anchor_source_rate": round(
            sum(row.get("capa_kaynaklarda") is True for row in rows) / len(rows),
            6,
        ),
        "quality_warning_disclosure_rate": round(
            sum(
                row.get("kalite_uyarisi_aciklandi") is True
                for row in quality_warning_rows
            )
            / len(quality_warning_rows),
            6,
        )
        if quality_warning_rows
        else None,
        "reasoning_zero_rate": round(
            sum(row.get("reasoning_tokens") == 0 for row in rows) / len(rows),
            6,
        ),
        "median_ms": round(statistics.median(timings), 3),
        "p95_ms": _percentile(timings, 0.95),
        "cases": rows,
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
    cases_path: Path = DEFAULT_CASES_PATH,
    clean_data_path: Path = DEFAULT_CLEAN_DATA,
    qdrant_path: Path = DEFAULT_QDRANT_PATH,
    output_path: Path = DEFAULT_OUTPUT,
    expected_points: int = DEFAULT_EXPECTED_POINTS,
    batch_size: int = 64,
    skip_chunk_comparison: bool = False,
    skip_rag: bool = False,
    embedding_client: EmbeddingClientProtocol | None = None,
    vector_store: VectorStoreProtocol | None = None,
) -> dict[str, Any]:
    """Run the complete local Day 20 evaluation and write an atomic report."""
    started = time.perf_counter()
    case_version, case_hash, cases = load_evaluation_cases(cases_path)
    client = embedding_client or LMStudioEmbeddingClient(
        base_url=DEFAULT_BASE_URL,
        model=DEFAULT_EMBEDDING_MODEL,
    )
    client.ensure_model_available()
    owned_store = vector_store is None
    store = vector_store or QdrantVectorStore(
        path=qdrant_path,
        collection_name=DEFAULT_COLLECTION_NAME,
        vector_size=DEFAULT_VECTOR_SIZE,
        embedding_model=client.model,
    )
    try:
        schema = dict(store.ensure_collection())
        point_count = store.count()
        if point_count != expected_points:
            raise Day20EvaluationError(
                f"Qdrant kayıt sayısı uyuşmuyor: {expected_points} yerine {point_count}"
            )

        embedding_started = time.perf_counter()
        query_vectors_list = client.embed_texts([case.query for case in cases])
        query_embedding_ms = round(
            (time.perf_counter() - embedding_started) * 1_000,
            3,
        )
        if len(query_vectors_list) != len(cases):
            raise Day20EvaluationError("Sorgu embedding sayısı uyuşmuyor")
        query_vectors = {
            case.case_id: vector
            for case, vector in zip(cases, query_vectors_list)
        }

        rankings_by_case: dict[str, list[dict[str, Any]]] = {}
        search_timings: list[float] = []
        for case in cases:
            search_started = time.perf_counter()
            hits = store.search(
                query_vectors[case.case_id],
                limit=SEARCH_LIMIT,
            )
            search_timings.append((time.perf_counter() - search_started) * 1_000)
            rankings_by_case[case.case_id] = decision_rankings(hits)

        comparisons = [
            evaluate_configuration(
                cases,
                rankings_by_case,
                top_k=top_k,
                threshold=threshold,
            )
            for top_k in TOP_K_VALUES
            for threshold in THRESHOLD_VALUES
        ]
        recommendation = choose_recommended_configuration(comparisons)
        current_metrics = evaluate_configuration(
            cases,
            rankings_by_case,
            top_k=DEFAULT_RAG_TOP_K,
            threshold=DEFAULT_RAG_MIN_SCORE,
        )
        errors = analyze_retrieval_errors(
            cases,
            rankings_by_case,
            top_k=int(recommendation["top_k"]),
            threshold=float(recommendation["minimum_score"]),
        )

        chunk_comparison = None
        if not skip_chunk_comparison:
            chunk_comparison = compare_chunk_configurations(
                cases,
                rankings_by_case,
                query_vectors,
                clean_data_path=clean_data_path,
                embedding_client=client,
                batch_size=batch_size,
            )

        rag_evaluation = None
        if not skip_rag:
            chat_client = LMStudioChatClient(
                base_url=DEFAULT_BASE_URL,
                model=DEFAULT_CHAT_MODEL,
            )
            chat_client.ensure_model_available()
            semantic_service = SemanticSearchService(
                embedding_client=client,
                vector_store=store,
                expected_point_count=expected_points,
            )
            rag_service = RAGAnswerService(
                semantic_search=semantic_service,
                chat_client=chat_client,
            )
            rag_evaluation = evaluate_rag_cases(
                cases,
                rag_service,
                top_k=int(recommendation["top_k"]),
                min_score=float(recommendation["minimum_score"]),
            )

        report = {
            "evaluation_version": EVALUATION_VERSION,
            "test_set": {
                "path": str(cases_path),
                "version": case_version,
                "sha256": case_hash,
                "case_count": len(cases),
                "in_domain_count": sum(case.is_in_domain for case in cases),
                "out_of_domain_count": sum(not case.is_in_domain for case in cases),
                "rag_case_count": sum(case.rag_test for case in cases),
            },
            "models": {
                "embedding": client.model,
                "chat": DEFAULT_CHAT_MODEL,
                "prompt_version": PROMPT_VERSION,
            },
            "qdrant": {
                "path": str(qdrant_path),
                "collection": store.collection_name,
                "point_count": point_count,
                "schema": schema,
            },
            "cases": [asdict(case) for case in cases],
            "decision_level_rankings": rankings_by_case,
            "current_configuration": current_metrics,
            "configuration_comparison": comparisons,
            "recommendation": recommendation,
            "retrieval_error_analysis": errors,
            "chunk_comparison": chunk_comparison,
            "rag_evaluation": rag_evaluation,
            "performance": {
                "query_batch_embedding_ms": query_embedding_ms,
                "semantic_search_median_ms": round(
                    statistics.median(search_timings), 3
                ),
                "semantic_search_p95_ms": _percentile(search_timings, 0.95),
                "total_evaluation_seconds": round(time.perf_counter() - started, 3),
            },
            "limitations": [
                "Çapa sorgular corpus kararlarından elle türetildiği için bağımsız kullanıcı testi değildir.",
                "Tek çapa karar etiketi, üst sıradaki diğer kararların ilgisiz olduğunu kanıtlamaz.",
                "Alan dışı örnekler Yargıtay yerine idari yargı kapsamındaki beş senaryoyla sınırlıdır.",
                "Chunk karşılaştırması tam yeniden indeksleme değil, gerçek zor negatiflerden oluşan aday havuzudur.",
                "Gemma yapısal güvenlik denetimleri hukuki uzman doğrulamasının yerini tutmaz.",
            ],
        }
        _atomic_write_json(output_path, report)
        return report
    finally:
        if owned_store:
            store.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="20. gün arama, chunk, RAG ve performans değerlendirmesi."
    )
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--clean-data", type=Path, default=DEFAULT_CLEAN_DATA)
    parser.add_argument("--qdrant-path", type=Path, default=DEFAULT_QDRANT_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--expected-points", type=int, default=DEFAULT_EXPECTED_POINTS)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--skip-chunk-comparison", action="store_true")
    parser.add_argument("--skip-rag", action="store_true")
    args = parser.parse_args()
    report = run_evaluation(
        cases_path=args.cases,
        clean_data_path=args.clean_data,
        qdrant_path=args.qdrant_path,
        output_path=args.output,
        expected_points=args.expected_points,
        batch_size=args.batch_size,
        skip_chunk_comparison=args.skip_chunk_comparison,
        skip_rag=args.skip_rag,
    )
    recommendation = report["recommendation"]
    print(f"Evaluation report: {args.output}")
    print(
        "Recommended retrieval: "
        f"top_k={recommendation['top_k']}, "
        f"min_score={recommendation['minimum_score']}, "
        f"anchor_recall={recommendation['capa_recall']}, "
        f"ood_rejection={recommendation['alan_disi_reddetme_orani']}"
    )
    if report["chunk_comparison"] is not None:
        chunk = report["chunk_comparison"]
        print(
            "Recommended chunking: "
            f"{chunk['onerilen_chunk_size']}/{chunk['onerilen_overlap']}"
        )
    if report["rag_evaluation"] is not None:
        rag = report["rag_evaluation"]
        print(
            "RAG cases: "
            f"completed={rag['completed_count']}, "
            f"safe_insufficient={rag['safe_insufficient_count']}, "
            f"failures={rag['failure_count']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
