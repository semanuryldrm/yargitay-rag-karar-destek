"""Run Day 19 HTTP and end-to-end checks against the live local API."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.semantic_search import MAX_QUERY_CHARACTERS  # noqa: E402


DEFAULT_API_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_TIMEOUT_SECONDS = 240.0
NORMAL_EVENT = (
    "İşveren belirsiz süreli iş sözleşmemi geçerli bir neden göstermeden "
    "feshetti. İşe iade ve işe başlatmama tazminatı talep edebilir miyim?"
)
LEGAL_CLOSING = (
    "Somut olayın özelliklerine göre sonuç değişebilir; bu değerlendirme "
    "hukuki danışmanlık değildir."
)


class EndToEndCheckError(RuntimeError):
    """Raised when a live Day 19 integration expectation is not met."""


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise EndToEndCheckError(message)


def _validate_base_url(value: str) -> str:
    normalized = value.strip().rstrip("/")
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise EndToEndCheckError(f"Geçersiz API adresi: {value!r}")
    return normalized


def _request_json(
    base_url: str,
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    timeout_seconds: float,
) -> tuple[int, dict[str, Any], float]:
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    request = Request(
        f"{base_url}{path}",
        data=body,
        headers=headers,
        method=method,
    )
    started = time.perf_counter()
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            status_code = response.status
            raw_body = response.read()
    except HTTPError as exc:
        status_code = exc.code
        raw_body = exc.read()
    except (URLError, TimeoutError, OSError) as exc:
        raise EndToEndCheckError(
            f"API isteği tamamlanamadı ({method} {path}): {exc}"
        ) from exc
    elapsed_ms = round((time.perf_counter() - started) * 1_000, 3)
    try:
        parsed = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EndToEndCheckError(
            f"API geçerli UTF-8 JSON döndürmedi ({method} {path})"
        ) from exc
    if not isinstance(parsed, dict):
        raise EndToEndCheckError(f"API nesne döndürmedi ({method} {path})")
    return status_code, parsed, elapsed_ms


def _long_event() -> str:
    seed = (
        "İş sözleşmesinin geçerli neden gösterilmeden feshedildiği, işe iade "
        "koşullarının ve tarafların iddialarının değerlendirildiği olay. "
    )
    value = (seed * ((MAX_QUERY_CHARACTERS // len(seed)) + 1))[
        :MAX_QUERY_CHARACTERS
    ]
    if value[-1].isspace():
        value = value[:-1] + "."
    _expect(len(value) == MAX_QUERY_CHARACTERS, "Uzun sorgu üretilemedi")
    return value


def _validate_error_response(
    status_code: int,
    response: dict[str, Any],
    *,
    name: str,
) -> None:
    _expect(status_code == 422, f"{name} isteği 422 dönmedi")
    detail = response.get("detail")
    _expect(isinstance(detail, dict), f"{name} hata ayrıntısı nesne değil")
    _expect(
        detail.get("code") == "request_validation_failed",
        f"{name} standart doğrulama hata kodunu dönmedi",
    )
    _expect(bool(detail.get("errors")), f"{name} alan hata listesini dönmedi")


def run_checks(
    *,
    base_url: str = DEFAULT_API_BASE_URL,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    base_url = _validate_base_url(base_url)
    _expect(timeout_seconds > 0, "Zaman aşımı pozitif olmalıdır")
    report: dict[str, Any] = {"base_url": base_url, "checks": {}}

    status_code, system, elapsed = _request_json(
        base_url,
        "GET",
        "/api/v1/system-status",
        timeout_seconds=timeout_seconds,
    )
    _expect(status_code == 200, "Sistem durumu 200 dönmedi")
    _expect(system.get("status") == "ok", "Sistem durumu ok değil")
    components = system.get("components")
    _expect(isinstance(components, dict), "Bileşen durumları eksik")
    for component in ("embedding", "vector_database", "gemma"):
        value = components.get(component)
        _expect(isinstance(value, dict), f"{component} durumu eksik")
        _expect(value.get("status") == "ok", f"{component} hazır değil")
    _expect(system.get("indexed_chunks") == 31_544, "Qdrant kayıt sayısı hatalı")
    report["checks"]["system_status"] = {
        "status": "passed",
        "elapsed_ms": elapsed,
        "indexed_chunks": system["indexed_chunks"],
    }

    error_cases = {
        "empty_query": {"olay": ""},
        "too_long_query": {"olay": "x" * (MAX_QUERY_CHARACTERS + 1)},
        "invalid_query": {"olay": NORMAL_EVENT, "top_k": 0, "unknown": True},
    }
    for name, payload in error_cases.items():
        code, response, elapsed = _request_json(
            base_url,
            "POST",
            "/api/v1/semantic-search",
            payload=payload,
            timeout_seconds=timeout_seconds,
        )
        _validate_error_response(code, response, name=name)
        report["checks"][name] = {"status": "passed", "elapsed_ms": elapsed}

    code, long_response, elapsed = _request_json(
        base_url,
        "POST",
        "/api/v1/semantic-search",
        payload={"olay": _long_event(), "top_k": 3, "min_score": 0.65},
        timeout_seconds=timeout_seconds,
    )
    _expect(code == 200, "Geçerli uzun sorgu 200 dönmedi")
    _expect(
        len(long_response.get("sorgu", "")) == MAX_QUERY_CHARACTERS,
        "Geçerli uzun sorgu API'de korunmadı",
    )
    report["checks"]["valid_long_query"] = {
        "status": "passed",
        "elapsed_ms": elapsed,
        "result_count": long_response.get("sonuc_sayisi"),
    }

    code, search, elapsed = _request_json(
        base_url,
        "POST",
        "/api/v1/semantic-search",
        payload={
            "olay": NORMAL_EVENT,
            "top_k": 5,
            "min_score": 0.65,
            "filtreler": {"karar_turu": "hukuk", "daire": "7. Hukuk Dairesi"},
        },
        timeout_seconds=timeout_seconds,
    )
    _expect(code == 200, "Normal semantik arama 200 dönmedi")
    results = search.get("sonuclar")
    _expect(isinstance(results, list) and len(results) >= 2, "Yeterli karar bulunmadı")
    decision_ids = [item.get("karar_id") for item in results]
    _expect(len(decision_ids) == len(set(decision_ids)), "Kararlar benzersiz değil")
    scores = [item.get("benzerlik_skoru") for item in results]
    _expect(scores == sorted(scores, reverse=True), "Sonuç skorları sıralı değil")
    report["checks"]["semantic_search"] = {
        "status": "passed",
        "elapsed_ms": elapsed,
        "result_count": len(results),
        "best_score": scores[0],
    }

    code, rag, elapsed = _request_json(
        base_url,
        "POST",
        "/api/v1/rag-answer",
        payload={
            "olay": NORMAL_EVENT,
            "top_k": 5,
            "min_score": 0.65,
            "filtreler": {"karar_turu": "hukuk", "daire": "7. Hukuk Dairesi"},
        },
        timeout_seconds=timeout_seconds,
    )
    _expect(code == 200, "RAG soru-cevap isteği 200 dönmedi")
    _expect(rag.get("durum") == "tamamlandi", "RAG değerlendirmesi tamamlanmadı")
    _expect(rag.get("llm_cagrildi") is True, "Gemma çağrısı doğrulanamadı")
    answer = rag.get("cevap")
    _expect(isinstance(answer, str) and "[K" in answer, "Cevapta kaynak yok")
    _expect(answer.endswith(LEGAL_CLOSING), "Cevap hukuki uyarıyla bitmiyor")
    stats = rag.get("model_istatistikleri")
    _expect(isinstance(stats, dict), "Gemma istatistikleri eksik")
    _expect(stats.get("reasoning_output_tokens") == 0, "Reasoning kapalı değil")
    _expect(
        rag.get("embedding_modeli") == system.get("embedding_model"),
        "Embedding modeli uçtan uca eşleşmiyor",
    )
    _expect(
        rag.get("koleksiyon") == system.get("qdrant_collection"),
        "Qdrant koleksiyonu uçtan uca eşleşmiyor",
    )
    _expect(
        rag.get("chat_modeli") == system.get("chat_model"),
        "Gemma modeli uçtan uca eşleşmiyor",
    )
    report["checks"]["rag_answer"] = {
        "status": "passed",
        "elapsed_ms": elapsed,
        "found_sources": rag.get("bulunan_kaynak_sayisi"),
        "cited_sources": rag.get("kullanilan_kaynak_sayisi"),
        "input_tokens": stats.get("input_tokens"),
        "output_tokens": stats.get("total_output_tokens"),
        "reasoning_tokens": stats.get("reasoning_output_tokens"),
    }

    report["status"] = "passed"
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="19. gün FastAPI ve gerçek RAG entegrasyon kontrollerini çalıştırır."
    )
    parser.add_argument("--base-url", default=DEFAULT_API_BASE_URL)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    args = parser.parse_args()
    try:
        report = run_checks(base_url=args.base_url, timeout_seconds=args.timeout)
    except EndToEndCheckError as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
