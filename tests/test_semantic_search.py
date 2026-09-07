import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.semantic_search import (
    QueryValidationError,
    SemanticSearchError,
    SemanticSearchService,
    normalize_query,
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

    def search(self, query_vector, *, limit=5, query_filter=None):
        self.search_calls.append((list(query_vector), limit, query_filter))
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
            "  İşveren sözleşmemi haksız şekilde feshetti.  ", top_k=2
        )

        self.assertEqual(embedding.queries, [
            "İşveren sözleşmemi haksız şekilde feshetti."
        ])
        self.assertEqual(store.search_calls, [([1.0, 0.0, 0.0], 2, None)])
        self.assertEqual(response["sonuc_sayisi"], 2)
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


if __name__ == "__main__":
    unittest.main()
