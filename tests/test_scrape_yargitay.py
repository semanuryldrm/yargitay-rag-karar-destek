import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from scrape_yargitay import (
    DecisionDataError,
    build_decision_record,
    extract_list_items,
    fetch_decision_page,
    write_jsonl,
)


SUMMARY = {
    "id": "123",
    "daire": "1. Hukuk Dairesi",
    "esasNo": "2025/10",
    "kararNo": "2025/20",
    "kararTarihi": "01.01.2025",
}


class FakeClient:
    def __init__(self, summaries=None, html="<html>Türkçe karar</html>"):
        self.summaries = summaries if summaries is not None else [SUMMARY]
        self.html = html
        self.detail_ids = []

    def list_decisions(self, **_kwargs):
        return {"data": {"data": self.summaries}}

    def get_decision(self, decision_id):
        self.detail_ids.append(decision_id)
        return {"data": self.html}


class ScrapeYargitayTests(unittest.TestCase):
    def test_extracts_list_items(self):
        self.assertEqual(extract_list_items({"data": {"data": [SUMMARY]}}), [SUMMARY])

    def test_rejects_invalid_list_shape(self):
        with self.assertRaises(DecisionDataError):
            extract_list_items({"data": None})

    def test_builds_normalized_record_and_preserves_html(self):
        record = build_decision_record(SUMMARY, {"data": "<p>İçtihat</p>"})
        self.assertEqual(record["id"], "123")
        self.assertEqual(record["esas_no"], "2025/10")
        self.assertEqual(record["karar_html"], "<p>İçtihat</p>")

    def test_rejects_missing_metadata(self):
        incomplete = dict(SUMMARY)
        incomplete["kararNo"] = ""
        with self.assertRaisesRegex(DecisionDataError, "kararNo"):
            build_decision_record(incomplete, {"data": "<p>Karar</p>"})

    def test_rejects_empty_detail_html(self):
        with self.assertRaisesRegex(DecisionDataError, "no detail HTML"):
            build_decision_record(SUMMARY, {"data": "  "})

    def test_fetches_each_detail_in_list_order(self):
        second = dict(SUMMARY, id="456", esasNo="2025/11")
        client = FakeClient([SUMMARY, second])
        records = fetch_decision_page(
            client,
            start_date="01.01.2025",
            end_date="01.12.2025",
            page_number=1,
            page_size=2,
        )
        self.assertEqual(client.detail_ids, ["123", "456"])
        self.assertEqual([record["id"] for record in records], ["123", "456"])

    def test_rejects_unexpected_record_count(self):
        with self.assertRaisesRegex(DecisionDataError, "Expected 2"):
            fetch_decision_page(
                FakeClient(),
                start_date="01.01.2025",
                end_date="01.12.2025",
                page_number=1,
                page_size=2,
            )

    def test_writes_utf8_jsonl(self):
        record = build_decision_record(SUMMARY, {"data": "<p>İçtihat</p>"})
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "sample.jsonl"
            write_jsonl([record], output)
            saved = json.loads(output.read_text(encoding="utf-8").strip())
        self.assertEqual(saved["karar_html"], "<p>İçtihat</p>")


if __name__ == "__main__":
    unittest.main()
