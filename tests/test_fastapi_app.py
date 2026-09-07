import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from app.main import create_app
from app.semantic_search import LEGAL_NOTICE, SemanticSearchError


class FakeSearchService:
    def __init__(self):
        self.calls = []

    def health(self):
        return {
            "status": "ok",
            "embedding_model": "test-embedding-model",
            "qdrant_collection": "test_collection",
            "indexed_chunks": 31_544,
        }

    def search(
        self,
        query,
        *,
        top_k=5,
        min_score=None,
        metadata_filters=None,
    ):
        self.calls.append((query, top_k, min_score, metadata_filters))
        return {
            "sorgu": query,
            "top_k": top_k,
            "aranan_aday_chunk_sayisi": top_k * 5,
            "minimum_benzerlik_skoru": min_score,
            "filtreler": metadata_filters or {},
            "sonuc_sayisi": 1,
            "yeterli_sonuc_bulundu": True,
            "embedding_modeli": "test-embedding-model",
            "koleksiyon": "test_collection",
            "sure_ms": 12.5,
            "uyari": LEGAL_NOTICE,
            "sonuclar": [
                {
                    "sira": 1,
                    "benzerlik_skoru": 0.81,
                    "chunk_id": "d1:c0001",
                    "karar_id": "d1",
                    "chunk_sirasi": 1,
                    "toplam_chunk": 1,
                    "daire": "7. Hukuk Dairesi",
                    "karar_turu": "hukuk",
                    "esas_no": "2013/2027",
                    "karar_no": "2013/1322",
                    "karar_tarihi": "01.02.2013",
                    "baslik": "İşe iade kararı",
                    "chunk_metni": "İş sözleşmesinin geçersiz feshi.",
                    "veri_kalite_uyarilari": [],
                    "kaynak": "TurkLegalBench",
                    "kaynak_url": "https://example.test/corpus",
                    "kaynak_lisans": "CC BY 4.0",
                }
            ],
        }


class FastAPIApplicationTests(unittest.TestCase):
    def test_health_and_semantic_search_contract(self):
        service = FakeSearchService()
        with TestClient(create_app(search_service=service)) as client:
            health = client.get("/health")
            response = client.post(
                "/api/v1/semantic-search",
                json={
                    "olay": "İşveren sözleşmemi geçerli neden göstermeden feshetti.",
                    "top_k": 3,
                    "min_score": 0.6,
                    "filtreler": {
                        "karar_turu": "hukuk",
                        "daire": " 7.  Hukuk Dairesi ",
                    },
                },
            )

        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["indexed_chunks"], 31_544)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["sonuc_sayisi"], 1)
        self.assertEqual(service.calls, [
            (
                "İşveren sözleşmemi geçerli neden göstermeden feshetti.",
                3,
                0.6,
                {"karar_turu": "hukuk", "daire": "7. Hukuk Dairesi"},
            )
        ])
        self.assertEqual(response.json()["minimum_benzerlik_skoru"], 0.6)
        self.assertEqual(response.json()["filtreler"]["karar_turu"], "hukuk")

    def test_request_validation_rejects_short_unknown_and_invalid_top_k(self):
        with TestClient(create_app(search_service=FakeSearchService())) as client:
            cases = (
                {"olay": "kısa", "top_k": 5},
                {"olay": "Geçerli uzunlukta olay açıklamasıdır.", "top_k": 21},
                {
                    "olay": "Geçerli uzunlukta olay açıklamasıdır.",
                    "top_k": 5,
                    "bilinmeyen": True,
                },
                {
                    "olay": "Geçerli uzunlukta olay açıklamasıdır.",
                    "min_score": 1.1,
                },
                {
                    "olay": "Geçerli uzunlukta olay açıklamasıdır.",
                    "filtreler": {"karar_turu": "idari"},
                },
                {
                    "olay": "Geçerli uzunlukta olay açıklamasıdır.",
                    "filtreler": {"bilinmeyen": "deger"},
                },
            )
            responses = [
                client.post("/api/v1/semantic-search", json=payload)
                for payload in cases
            ]

        self.assertTrue(all(response.status_code == 422 for response in responses))

    def test_dependency_failure_returns_structured_503(self):
        class FailingSearchService(FakeSearchService):
            def search(
                self,
                query,
                *,
                top_k=5,
                min_score=None,
                metadata_filters=None,
            ):
                raise SemanticSearchError("LM Studio bağlantısı kurulamadı")

        with TestClient(create_app(search_service=FailingSearchService())) as client:
            response = client.post(
                "/api/v1/semantic-search",
                json={"olay": "İşveren sözleşmemi haksız biçimde feshetti."},
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json()["detail"]["code"], "semantic_search_failed"
        )


if __name__ == "__main__":
    unittest.main()
