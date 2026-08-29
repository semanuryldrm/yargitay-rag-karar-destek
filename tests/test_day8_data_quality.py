import json
import logging
import sys
import tempfile
import unicodedata
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from scrape_yargitay import (
    DecisionDataError,
    build_decision_record,
    classify_decision_type,
    extract_list_items,
    extract_validated_list_page,
    load_existing_ids,
    run_scraper,
)
from yargitay_client import YargitayClient, YargitayClientError


SUMMARY = {
    "id": "123",
    "daire": "1. Hukuk Dairesi",
    "esasNo": "2025/10",
    "kararNo": "2025/20",
    "kararTarihi": "01.01.2025",
}


class RawResponse:
    status = 200

    def __init__(self, payload: bytes):
        self._stream = BytesIO(payload)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self._stream.read()


class EmptyTerminalPageClient:
    def list_decisions(self, **_kwargs):
        return {"data": {"data": [], "recordsFiltered": 0}}

    def get_decision(self, _decision_id):
        raise AssertionError("No detail request should be sent for an empty terminal page")

    def reset_session(self):
        pass


class RecoveringContentClient:
    def __init__(self):
        self.detail_calls = 0
        self.reset_count = 0

    def list_decisions(self, **_kwargs):
        return {"data": {"data": [SUMMARY], "recordsFiltered": 1}}

    def get_decision(self, _decision_id):
        self.detail_calls += 1
        if self.detail_calls == 1:
            return {"data": "geçici bozuk düz metin"}
        return {"data": "<p>Geçerli karar metni</p>"}

    def reset_session(self):
        self.reset_count += 1


class Day8DataQualityTests(unittest.TestCase):
    def setUp(self):
        self.logger = logging.getLogger(f"test-{self.id()}")
        self.logger.addHandler(logging.NullHandler())

    def test_classifies_hukuk_ceza_kurul_and_unknown_types(self):
        self.assertEqual(classify_decision_type("3. Hukuk Dairesi"), "hukuk")
        self.assertEqual(classify_decision_type("7. Ceza Dairesi"), "ceza")
        self.assertEqual(classify_decision_type("Hukuk Genel Kurulu"), "kurul")
        self.assertEqual(classify_decision_type("Başkanlar Kurulu"), "kurul")
        self.assertEqual(classify_decision_type("Bilinmeyen Birim"), "diger")

    def test_normalizes_metadata_and_preserves_turkish_html(self):
        summary = dict(
            SUMMARY,
            daire="  1.\u00a0Hukuk   Dairesi ",
            kararNo=unicodedata.normalize("NFD", "2025/Ç20"),
        )
        html = "<p>Türkçe İçtihat: ğüşöçıİ</p>"
        record = build_decision_record(summary, {"data": html})
        self.assertEqual(record["daire"], "1. Hukuk Dairesi")
        self.assertEqual(record["karar_no"], "2025/Ç20")
        self.assertEqual(record["karar_turu"], "hukuk")
        self.assertEqual(record["karar_html"], html)

    def test_rejects_non_object_list_record(self):
        with self.assertRaisesRegex(DecisionDataError, "not an object"):
            extract_list_items({"data": {"data": ["broken"]}})

    def test_accepts_partial_final_page_when_count_matches(self):
        response = {"data": {"data": [SUMMARY], "recordsFiltered": 3}}
        items = extract_validated_list_page(response, page_number=2, page_size=2)
        self.assertEqual(items, [SUMMARY])

    def test_rejects_short_nonterminal_page(self):
        response = {"data": {"data": [SUMMARY], "recordsFiltered": 10}}
        with self.assertRaisesRegex(DecisionDataError, "Expected 2 terminal-page"):
            extract_validated_list_page(response, page_number=1, page_size=2)

    def test_accepts_empty_page_after_last_record(self):
        response = {"data": {"data": [], "recordsFiltered": 2}}
        items = extract_validated_list_page(response, page_number=2, page_size=2)
        self.assertEqual(items, [])

    def test_rejects_replacement_character_in_metadata(self):
        summary = dict(SUMMARY, daire="1. Hukuk Dairesi �")
        with self.assertRaisesRegex(DecisionDataError, "invalid characters"):
            build_decision_record(summary, {"data": "<p>Karar</p>"})

    def test_rejects_plain_text_detail(self):
        with self.assertRaisesRegex(DecisionDataError, "is not HTML"):
            build_decision_record(SUMMARY, {"data": "Bu içerik HTML değildir."})

    def test_rejects_html_without_visible_text(self):
        with self.assertRaisesRegex(DecisionDataError, "no visible text"):
            build_decision_record(
                SUMMARY, {"data": "<style>p{color:red}</style><script>1</script>"}
            )

    def test_rejects_replacement_character_in_detail(self):
        with self.assertRaisesRegex(DecisionDataError, "invalid characters"):
            build_decision_record(SUMMARY, {"data": "<p>Bozuk � metin</p>"})

    def test_load_existing_ids_rejects_invalid_utf8(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "decisions.jsonl"
            output.write_bytes(b'{"id":"1","text":"\xff"}\n')
            with self.assertRaisesRegex(DecisionDataError, "not valid UTF-8"):
                load_existing_ids(output)

    def test_client_accepts_utf8_bom_and_turkish_characters(self):
        payload = json.dumps(
            {"data": "<p>İçtihat ğüşöçı</p>"}, ensure_ascii=False
        ).encode("utf-8")
        client = YargitayClient()
        client._session_ready = True
        with patch.object(
            client._opener, "open", return_value=RawResponse(b"\xef\xbb\xbf" + payload)
        ):
            result = client.get_decision("123")
        self.assertEqual(result["data"], "<p>İçtihat ğüşöçı</p>")

    def test_client_rejects_invalid_utf8_bytes(self):
        client = YargitayClient()
        client._session_ready = True
        with patch.object(
            client._opener,
            "open",
            return_value=RawResponse(b'{"data":"\xff"}'),
        ):
            with self.assertRaisesRegex(YargitayClientError, "valid UTF-8 JSON"):
                client.get_decision("123")

    def test_client_wraps_connection_reset(self):
        client = YargitayClient()
        client._session_ready = True
        with patch.object(
            client._opener, "open", side_effect=ConnectionResetError("reset")
        ):
            with self.assertRaisesRegex(YargitayClientError, "request failed"):
                client.get_decision("123")

    def test_scraper_stops_cleanly_at_empty_terminal_page(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = run_scraper(
                EmptyTerminalPageClient(),
                start_date="01.01.2025",
                end_date="01.12.2025",
                page_size=2,
                max_pages=1,
                output_path=root / "decisions.jsonl",
                state_path=root / "state.json",
                logger=self.logger,
                request_delay=0,
                retry_delay=0,
                sleep_fn=lambda _seconds: None,
            )
        self.assertEqual(state, {"last_completed_page": 0, "total_saved": 0})

    def test_scraper_retries_temporarily_malformed_detail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client = RecoveringContentClient()
            state = run_scraper(
                client,
                start_date="01.01.2025",
                end_date="01.12.2025",
                page_size=1,
                max_pages=1,
                output_path=root / "decisions.jsonl",
                state_path=root / "state.json",
                logger=self.logger,
                attempts=2,
                request_delay=0,
                retry_delay=0,
                sleep_fn=lambda _seconds: None,
            )
        self.assertEqual(client.detail_calls, 2)
        self.assertEqual(client.reset_count, 1)
        self.assertEqual(state, {"last_completed_page": 1, "total_saved": 1})


if __name__ == "__main__":
    unittest.main()
