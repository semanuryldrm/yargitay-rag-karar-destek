import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.rag_answer import (
    RAGAnswerError,
    RAGAnswerService,
    STANDARD_INSUFFICIENT_ANSWER,
    SYSTEM_PROMPT,
    ensure_quality_limit_disclosure,
    prepare_sources,
    validate_grounded_answer,
)
from scripts.lmstudio_chat import ChatClientError, ChatGeneration


CLOSING_NOTICE = (
    "Somut olayın özelliklerine göre sonuç değişebilir; bu değerlendirme "
    "hukuki danışmanlık değildir."
)


def search_result(decision_id, *, score=0.72, chamber="7. Hukuk Dairesi"):
    return {
        "sira": 1,
        "benzerlik_skoru": score,
        "chunk_id": f"{decision_id}:c0001",
        "karar_id": decision_id,
        "daire": chamber,
        "esas_no": "2013/2027",
        "karar_no": "2013/1322",
        "karar_tarihi": "20.02.2013",
        "baslik": f"{chamber} örnek karar",
        "chunk_metni": "Fesih nedeninin açıkça belirtilmesi gerektiği incelenmiştir.",
        "veri_kalite_uyarilari": [],
        "kaynak": "TurkLegalBench",
        "kaynak_url": "https://example.test/corpus",
        "kaynak_lisans": "CC BY 4.0",
    }


class FakeSemanticSearch:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def search(self, query, *, top_k=5, min_score=0.65, metadata_filters=None):
        self.calls.append((query, top_k, min_score, metadata_filters))
        return {
            "sorgu": " ".join(query.split()),
            "filtreler": metadata_filters or {},
            "embedding_modeli": "test-embedding-model",
            "koleksiyon": "test_collection",
            "sonuclar": self.results[:top_k],
        }


class FakeChatClient:
    model = "google/gemma-4-12b-qat"

    def __init__(self, text=None):
        self.text = text or (
            "Değerlendirme\nFesih nedeninin açıklığı incelenmiştir [K1]. "
            "Benzer yaklaşım ikinci kararda da görülmektedir [K2].\n\n"
            "Sınırlamalar\nKaynaklarda tazminat miktarı bulunmamaktadır.\n"
            + CLOSING_NOTICE
        )
        self.calls = []
        self.model_checks = 0

    def ensure_model_available(self):
        self.model_checks += 1
        return (self.model,)

    def generate(self, *, system_prompt, input_text, max_output_tokens):
        self.calls.append((system_prompt, input_text, max_output_tokens))
        return ChatGeneration(
            text=self.text,
            model=self.model,
            response_id="resp_test",
            stats={
                "input_tokens": 300,
                "total_output_tokens": 80,
                "reasoning_output_tokens": 0,
            },
        )


class RAGAnswerTests(unittest.TestCase):
    def test_retrieves_sources_builds_strict_prompt_and_returns_citations(self):
        search = FakeSemanticSearch(
            [search_result("d1"), search_result("d2", score=0.70)]
        )
        chat = FakeChatClient()
        service = RAGAnswerService(semantic_search=search, chat_client=chat)

        response = service.answer(
            "  İşveren sözleşmemi gerekçesiz feshetti.  ",
            top_k=5,
            min_score=0.65,
            metadata_filters={"karar_turu": "hukuk"},
        )

        self.assertEqual(response["durum"], "tamamlandi")
        self.assertTrue(response["degerlendirme_uretildi"])
        self.assertTrue(response["llm_cagrildi"])
        self.assertEqual(response["kullanilan_kaynak_sayisi"], 2)
        self.assertEqual(response["model_response_id"], "resp_test")
        self.assertEqual(response["embedding_modeli"], "test-embedding-model")
        self.assertEqual(response["koleksiyon"], "test_collection")
        self.assertEqual(
            [source["kaynak_etiketi"] for source in response["kaynaklar"]],
            ["K1", "K2"],
        )
        self.assertEqual(
            search.calls,
            [
                (
                    "  İşveren sözleşmemi gerekçesiz feshetti.  ",
                    5,
                    0.65,
                    {"karar_turu": "hukuk"},
                )
            ],
        )
        system_prompt, input_text, token_limit = chat.calls[0]
        self.assertEqual(system_prompt, SYSTEM_PROMPT)
        self.assertIn("yalnızca", system_prompt.casefold())
        self.assertIn("[K1]", input_text)
        self.assertIn("2013/2027", input_text)
        self.assertIn("Fesih nedeninin", input_text)
        self.assertEqual(token_limit, 800)
        self.assertEqual(response["model_cagri_sayisi"], 1)

    def test_insufficient_sources_skip_gemma_and_return_standard_answer(self):
        chat = FakeChatClient()
        service = RAGAnswerService(
            semantic_search=FakeSemanticSearch([search_result("d1")]),
            chat_client=chat,
        )

        response = service.answer("İmar planının iptalini talep ediyorum.")

        self.assertEqual(response["durum"], "yetersiz_kaynak")
        self.assertFalse(response["degerlendirme_uretildi"])
        self.assertFalse(response["llm_cagrildi"])
        self.assertEqual(response["cevap"], STANDARD_INSUFFICIENT_ANSWER)
        self.assertEqual(response["bulunan_kaynak_sayisi"], 1)
        self.assertEqual(chat.calls, [])
        self.assertIsNone(response["model_response_id"])
        self.assertEqual(response["model_cagri_sayisi"], 0)

    def test_health_checks_live_chat_model(self):
        chat = FakeChatClient()
        service = RAGAnswerService(
            semantic_search=FakeSemanticSearch([]),
            chat_client=chat,
        )
        self.assertEqual(service.health()["chat_model"], chat.model)
        self.assertEqual(chat.model_checks, 1)

        class UnavailableChatClient(FakeChatClient):
            def ensure_model_available(self):
                raise ChatClientError("Gemma modeli kullanılamıyor")

        unavailable = RAGAnswerService(
            semantic_search=FakeSemanticSearch([]),
            chat_client=UnavailableChatClient(),
        )
        with self.assertRaisesRegex(RAGAnswerError, "kullanılamıyor"):
            unavailable.health()

    def test_rejects_missing_pipeline_metadata(self):
        search = FakeSemanticSearch([search_result("d1"), search_result("d2")])
        chat = FakeChatClient()
        service = RAGAnswerService(semantic_search=search, chat_client=chat)

        original_search = search.search

        def search_without_metadata(*args, **kwargs):
            response = original_search(*args, **kwargs)
            response.pop("embedding_modeli")
            return response

        search.search = search_without_metadata
        with self.assertRaisesRegex(RAGAnswerError, "embedding modeli"):
            service.answer("İş sözleşmem gerekçesiz şekilde feshedildi.")

    def test_rejects_unknown_citation_and_definitive_outcome(self):
        unknown = f"Değerlendirme [K9].\nSınırlamalar\n{CLOSING_NOTICE}"
        certain = (
            "Değerlendirme\nDavayı kesin kazanırsınız [K1].\n"
            f"Sınırlamalar\n{CLOSING_NOTICE}"
        )
        with self.assertRaisesRegex(RAGAnswerError, "bilinmeyen"):
            validate_grounded_answer(unknown, {"K1", "K2"})
        with self.assertRaisesRegex(RAGAnswerError, "kesin hukuki"):
            validate_grounded_answer(certain, {"K1", "K2"})
        grouped = (
            "Değerlendirme\nOrtak tespit [K1, K2].\n"
            f"Sınırlamalar\n{CLOSING_NOTICE}"
        )
        self.assertEqual(
            validate_grounded_answer(grouped, {"K1", "K2"}), grouped
        )

    def test_rejects_missing_citation_warning_and_duplicate_decision(self):
        with self.assertRaisesRegex(RAGAnswerError, "kaynak etiketi"):
            validate_grounded_answer(
                f"Değerlendirme.\nSınırlamalar.\n{CLOSING_NOTICE}", {"K1"}
            )
        with self.assertRaisesRegex(RAGAnswerError, "zorunlu hukuki uyarı"):
            validate_grounded_answer("Değerlendirme [K1].", {"K1"})
        with self.assertRaisesRegex(RAGAnswerError, "Tekrarlanan"):
            prepare_sources([search_result("d1"), search_result("d1")])

    def test_rejects_invalid_score_and_data_quality_warnings(self):
        invalid_score = search_result("d1", score=float("nan"))
        with self.assertRaisesRegex(RAGAnswerError, "benzerlik skoru"):
            prepare_sources([invalid_score])

        invalid_warnings = search_result("d2")
        invalid_warnings["veri_kalite_uyarilari"] = "uyarı"
        with self.assertRaisesRegex(RAGAnswerError, "veri kalitesi"):
            prepare_sources([invalid_warnings])

    def test_includes_data_quality_warnings_in_model_context(self):
        warned = search_result("d1")
        warned["veri_kalite_uyarilari"] = ["karar metni kaynakta kesilmiş"]

        sources, context = prepare_sources([warned])

        self.assertEqual(
            sources[0]["veri_kalite_uyarilari"],
            ["karar metni kaynakta kesilmiş"],
        )
        self.assertIn(
            "Veri kalitesi uyarıları: kaynakta belirtilen ek bir veri kalitesi uyarısı bulunuyor",
            context,
        )
        self.assertIn("kararın tam metni gibi sunma", SYSTEM_PROMPT)

    def test_adds_deterministic_quality_note_when_model_omits_it(self):
        warned = search_result("d1")
        warned["veri_kalite_uyarilari"] = [
            "kaynak_metin_2000_karakter_sinirinda"
        ]
        sources, _ = prepare_sources([warned])
        answer = (
            "Değerlendirme\nKaynakta fesih incelenmiştir [K1].\n\n"
            f"Sınırlamalar\nKaynakta miktar yoktur.\n{CLOSING_NOTICE}"
        )

        disclosed = ensure_quality_limit_disclosure(answer, sources)

        self.assertIn("Veri kalitesi notu: [K1]", disclosed)
        self.assertIn("2.000 karakter sınırında", disclosed)
        self.assertTrue(disclosed.endswith(CLOSING_NOTICE))

    def test_retries_once_when_first_model_answer_is_invalid(self):
        class RetryChatClient(FakeChatClient):
            def generate(self, *, system_prompt, input_text, max_output_tokens):
                self.calls.append((system_prompt, input_text, max_output_tokens))
                if len(self.calls) == 1:
                    text = "Değerlendirme\nEksik kapanış [K1]."
                else:
                    text = (
                        "Değerlendirme\nKaynaklar birlikte incelenmiştir [K1, K2].\n\n"
                        f"Sınırlamalar\nKaynakta ayrıntı yoktur.\n{CLOSING_NOTICE}"
                    )
                return ChatGeneration(
                    text=text,
                    model=self.model,
                    response_id=f"resp_{len(self.calls)}",
                    stats={"reasoning_output_tokens": 0},
                )

        chat = RetryChatClient()
        service = RAGAnswerService(
            semantic_search=FakeSemanticSearch(
                [search_result("d1"), search_result("d2")]
            ),
            chat_client=chat,
        )

        response = service.answer("İş sözleşmem gerekçesiz biçimde feshedildi.")

        self.assertEqual(response["model_cagri_sayisi"], 2)
        self.assertEqual(response["model_response_id"], "resp_2")
        self.assertIn("ÖNCEKİ YANIT", chat.calls[1][1])


if __name__ == "__main__":
    unittest.main()
