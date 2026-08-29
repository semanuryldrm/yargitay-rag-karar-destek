import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from import_turklegalbench import (
    ExternalCorpusError,
    convert_record,
    download_source,
    import_corpus,
)


def source_record(decision_id="d1", *, chamber="10.Hukuk Dairesi", text="Karar"):
    return {
        "_id": decision_id,
        "title": "10. Hukuk Dairesi - E. 2024/1, K. 2024/2",
        "text": text,
        "metadata": {
            "kurul": chamber,
            "esas_no": "2024/1",
            "karar_no": "2024/2",
            "tarih": "01.02.2024",
        },
    }


def write_source(path, records):
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )


class TurkLegalBenchImportTests(unittest.TestCase):
    def test_converts_plain_text_and_adds_explicit_provenance(self):
        record = convert_record(
            source_record(text="Türkçe\r\nkarar metni"), line_number=1
        )
        self.assertEqual(record["daire"], "10. Hukuk Dairesi")
        self.assertEqual(record["karar_turu"], "hukuk")
        self.assertEqual(record["karar_metni"], "Türkçe\nkarar metni")
        self.assertNotIn("karar_html", record)
        self.assertEqual(record["kaynak"], "IremTRNL/TurkLegalBench")
        self.assertEqual(record["kaynak_lisans"], "CC BY 4.0")

    def test_marks_missing_metadata_as_null_and_2000_character_limit(self):
        raw = source_record(text="a" * 2000)
        raw["metadata"]["esas_no"] = "-"
        raw["metadata"]["tarih"] = "-"
        record = convert_record(raw, line_number=1)
        self.assertIsNone(record["esas_no"])
        self.assertIsNone(record["karar_tarihi"])
        self.assertTrue(record["metin_2000_karakter_sinirinda"])

    def test_repairs_windows_c1_apostrophe_but_rejects_other_controls(self):
        repaired = convert_record(
            source_record(text="Kanun\u0092un maddesi"), line_number=1
        )
        self.assertEqual(repaired["karar_metni"], "Kanun’un maddesi")
        with self.assertRaisesRegex(ExternalCorpusError, "Control characters"):
            convert_record(source_record(text="Bozuk\x01metin"), line_number=1)

    def test_rejects_unknown_or_non_yargitay_chamber(self):
        with self.assertRaisesRegex(ExternalCorpusError, "Non-Yargitay"):
            convert_record(
                source_record(chamber="Danıştay 8. Dairesi"), line_number=1
            )

    def test_rejects_invalid_json_and_leaves_no_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.jsonl"
            output = root / "output.jsonl"
            source.write_text('{"broken":\n', encoding="utf-8")
            with self.assertRaisesRegex(ExternalCorpusError, "Invalid JSON"):
                import_corpus(source, output)
            self.assertFalse(output.exists())
            self.assertFalse(output.with_suffix(".jsonl.tmp").exists())

    def test_rejects_duplicate_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.jsonl"
            write_source(source, [source_record(), source_record()])
            with self.assertRaisesRegex(ExternalCorpusError, "Duplicate decision id"):
                import_corpus(source, root / "output.jsonl")

    def test_checks_hash_count_and_returns_quality_totals(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.jsonl"
            output = root / "output.jsonl"
            second = source_record("d2", chamber="Ceza Genel Kurulu", text="b" * 2000)
            second["metadata"]["karar_no"] = "-"
            write_source(source, [source_record(), second])
            expected_hash = hashlib.sha256(source.read_bytes()).hexdigest()
            stats = import_corpus(
                source,
                output,
                expected_count=2,
                expected_sha256=expected_hash,
            )
            saved = [json.loads(line) for line in output.read_text().splitlines()]
        self.assertEqual(stats["total_records"], 2)
        self.assertEqual(stats["unique_ids"], 2)
        self.assertEqual(stats["missing_karar_no"], 1)
        self.assertEqual(stats["texts_at_2000_character_limit"], 1)
        self.assertEqual(saved[1]["karar_turu"], "kurul")

    def test_rejects_hash_and_count_mismatches(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.jsonl"
            write_source(source, [source_record()])
            with self.assertRaisesRegex(ExternalCorpusError, "SHA-256 mismatch"):
                import_corpus(source, root / "hash.jsonl", expected_sha256="0" * 64)
            with self.assertRaisesRegex(ExternalCorpusError, "Record count mismatch"):
                import_corpus(source, root / "count.jsonl", expected_count=2)

    def test_download_publishes_only_hash_verified_content(self):
        payload = b'{"sample": true}\n'
        expected_hash = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "source.jsonl"
            with patch("import_turklegalbench.urlopen", return_value=io.BytesIO(payload)):
                downloaded = download_source(
                    destination, expected_sha256=expected_hash
                )
            self.assertEqual(downloaded, len(payload))
            self.assertEqual(destination.read_bytes(), payload)

            destination.write_bytes(b"previous")
            with patch("import_turklegalbench.urlopen", return_value=io.BytesIO(payload)):
                with self.assertRaisesRegex(ExternalCorpusError, "SHA-256 mismatch"):
                    download_source(destination, expected_sha256="0" * 64)
            self.assertEqual(destination.read_bytes(), b"previous")
            self.assertFalse(destination.with_suffix(".jsonl.download").exists())


if __name__ == "__main__":
    unittest.main()
