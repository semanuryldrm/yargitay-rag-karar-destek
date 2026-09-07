import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.semantic_search import (
    QueryValidationError,
    SemanticSearchError,
    SemanticSearchService,
    normalize_metadata_filters,
    normalize_query,
    validate_min_score,
    validate_top_k,
)
from scripts.lmstudio_embeddings import EmbeddingClientError
from scripts.qdrant_vector_store import SearchHit


class FakeEmbeddingClient:
    model = "test-embedding-model"
    base_url = "http://127.0.0.1:1234"

    def __init__(self):
        self.queries = []

    def embed_text(self, text):
        self.queries.append(text)
        return [1.0, 0.0, 0.0]


class FakeVectorStore:
    collection_name = "test_collection"

    def __init__(self, hits, count=3):
        self.hits = tuple(hits)
        self.point_count = count
        self.search_calls = []

    def search(
        self,
        query_vector,
        *,
        limit=5,
        metadata_filters=None,
        score_threshold=None,
    ):
        self.search_calls.append(
            (list(query_vector), limit, metadata_filters, score_threshold)
        )
        return self.hits[:limit]

    def count(self):
        return self.point_count


def result_payload(chunk_id, text="İş sözleşmesinin geçersiz feshi incelenmiştir."):
    return {
        "chunk_id": chunk_id,
        "karar_id": chunk_id.split(":", 1)[0],
        "chunk_sirasi": 1,
        "toplam_chunk": 2,
        "daire": "7. Hukuk Dairesi",
        "karar_turu": "hukuk",
        "esas_no": "2013/2027",
        "karar_no": "2013/1322",
        "karar_tarihi": "01.02.2013",
        "baslik": "İşe iade kararı",
        "chunk_metni": text,
        "veri_kalite_uyarilari": [],
        "kaynak": "TurkLegalBench",
        "kaynak_url": "https://example.test/corpus",
        "kaynak_lisans": "CC BY 4.0",
    }


class SemanticSearchTests(unittest.TestCase):
    def test_normalizes_query_and_validates_limits(self):
        self.assertEqual(
            normalize_query("  İşveren\n sözleşmemi   feshetti.  "),
            "İşveren sözleşmemi feshetti.",
        )
        self.assertEqual(validate_top_k(1), 1)
        self.assertEqual(validate_top_k(20), 20)
        with self.assertRaises(QueryValidationError):
            normalize_query("kısa")
        with self.assertRaises(QueryValidationError):
            normalize_query("x" * 4001)
        with self.assertRaises(QueryValidationError):
            validate_top_k(0)
        with self.assertRaises(QueryValidationError):
            validate_top_k(True)
        self.assertEqual(validate_min_score(0.6), 0.6)
        self.assertIsNone(validate_min_score(None))
        with self.assertRaises(QueryValidationError):
            validate_min_score(float("nan"))
        with self.assertRaises(QueryValidationError):
            validate_min_score(1.1)

    def test_normalizes_allow_listed_metadata_filters(self):
        self.assertEqual(
            normalize_metadata_filters(
                {
                    "karar_turu": "hukuk",
                    "daire": "  7.   Hukuk Dairesi ",
                    "veri_kalite_durumu": "gecerli",
                    "metin_2000_karakter_sinirinda": False,
                }
            ),
            {
                "karar_turu": "hukuk",
                "daire": "7. Hukuk Dairesi",
                "veri_kalite_durumu": "gecerli",
                "metin_2000_karakter_sinirinda": False,
            },
        )
        for invalid in (
            {"bilinmeyen": "deger"},
            {"karar_turu": "idari"},
            {"veri_kalite_durumu": "kotu"},
            {"metin_2000_karakter_sinirinda": "false"},
            {"daire": "   "},
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(QueryValidationError):
                    normalize_metadata_filters(invalid)

    def test_embeds_query_and_returns_ranked_source_metadata(self):
        hits = (
            SearchHit("d1:c0001", 0.81234567, result_payload("d1:c0001")),
            SearchHit("d2:c0001", 0.701, result_payload("d2:c0001")),
        )
        embedding = FakeEmbeddingClient()
        store = FakeVectorStore(hits)
        service = SemanticSearchService(
            embedding_client=embedding,
            vector_store=store,
            expected_point_count=3,
        )

        response = service.search(
            "  İşveren sözleşmemi haksız şekilde feshetti.  ",
            top_k=2,
            min_score=0.6,
            metadata_filters={"karar_turu": "hukuk"},
        )

        self.assertEqual(embedding.queries, [
            "İşveren sözleşmemi haksız şekilde feshetti."
        ])
        self.assertEqual(
            store.search_calls,
            [([1.0, 0.0, 0.0], 10, {"karar_turu": "hukuk"}, 0.6)],
        )
        self.assertEqual(response["sonuc_sayisi"], 2)
        self.assertEqual(response["aranan_aday_chunk_sayisi"], 10)
        self.assertTrue(response["yeterli_sonuc_bulundu"])
        self.assertEqual(response["minimum_benzerlik_skoru"], 0.6)
        self.assertEqual(response["filtreler"], {"karar_turu": "hukuk"})
        self.assertEqual(response["sonuclar"][0]["sira"], 1)
        self.assertEqual(response["sonuclar"][0]["benzerlik_skoru"], 0.812346)
        self.assertEqual(response["sonuclar"][0]["kaynak_lisans"], "CC BY 4.0")

    def test_health_requires_exact_index_count(self):
        service = SemanticSearchService(
            embedding_client=FakeEmbeddingClient(),
            vector_store=FakeVectorStore((), count=31_543),
            expected_point_count=31_544,
        )
        with self.assertRaisesRegex(SemanticSearchError, "point count mismatch"):
            service.health()

    def test_rejects_corrupt_qdrant_payload(self):
        cases = (
            ("kaynak", "", "kaynak"),
            ("chunk_sirasi", 0, "chunk_sirasi"),
            ("chunk_sirasi", 3, "toplam_chunk"),
        )
        for field, value, error_text in cases:
            with self.subTest(field=field, value=value):
                payload = result_payload("d1:c0001")
                payload[field] = value
                service = SemanticSearchService(
                    embedding_client=FakeEmbeddingClient(),
                    vector_store=FakeVectorStore(
                        (SearchHit("d1:c0001", 0.8, payload),)
                    ),
                    expected_point_count=1,
                )
                with self.assertRaisesRegex(SemanticSearchError, error_text):
                    service.search("İşveren sözleşmemi geçersiz feshetti.")

    def test_wraps_embedding_dependency_failure(self):
        class FailingEmbeddingClient(FakeEmbeddingClient):
            def embed_text(self, text):
                raise EmbeddingClientError("LM Studio kapalı")

        service = SemanticSearchService(
            embedding_client=FailingEmbeddingClient(),
            vector_store=FakeVectorStore(()),
            expected_point_count=3,
        )
        with self.assertRaisesRegex(SemanticSearchError, "LM Studio kapalı"):
            service.search("İşveren sözleşmemi geçersiz feshetti.")

    def test_empty_thresholded_search_is_explicit(self):
        service = SemanticSearchService(
            embedding_client=FakeEmbeddingClient(),
            vector_store=FakeVectorStore(()),
            expected_point_count=3,
        )
        response = service.search(
            "İşveren sözleşmemi geçersiz feshetti.", min_score=0.75
        )
        self.assertEqual(response["sonuc_sayisi"], 0)
        self.assertFalse(response["yeterli_sonuc_bulundu"])

    def test_returns_only_highest_scoring_chunk_per_decision(self):
        hits = (
            SearchHit("d1:c0001", 0.9, result_payload("d1:c0001")),
            SearchHit("d1:c0002", 0.8, result_payload("d1:c0002")),
            SearchHit("d2:c0001", 0.7, result_payload("d2:c0001")),
        )
        service = SemanticSearchService(
            embedding_client=FakeEmbeddingClient(),
            vector_store=FakeVectorStore(hits),
            expected_point_count=3,
        )
        response = service.search(
            "İşveren sözleşmemi geçersiz feshetti.", top_k=2
        )
        self.assertEqual(
            [item["karar_id"] for item in response["sonuclar"]], ["d1", "d2"]
        )


if __name__ == "__main__":
    unittest.main()
