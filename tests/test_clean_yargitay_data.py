import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from clean_yargitay_data import (
    DataCleaningError,
    clean_corpus,
    clean_decision_text,
)


def raw_record(
    decision_id="d1",
    *,
    chamber="1. Hukuk Dairesi",
    case_number="2024/1",
    decision_number="2024/2",
    decision_date="01.02.2024",
    text="İçtihat Metni\"\n\nKarar metni",
):
    return {
        "id": decision_id,
        "mahkeme": "Yargıtay",
        "daire": chamber,
        "karar_turu": "hukuk",
        "esas_no": case_number,
        "karar_no": decision_number,
        "karar_tarihi": decision_date,
        "baslik": f"{chamber} - E. {case_number}, K. {decision_number}",
        "karar_metni": text,
        "metin_2000_karakter_sinirinda": len(text) == 2000,
        "kaynak": "IremTRNL/TurkLegalBench",
        "kaynak_url": "https://example.test/dataset",
        "kaynak_lisans": "CC BY 4.0",
        "kaynak_kayit_id": decision_id,
    }


def write_jsonl(path, records):
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )


def run_clean(root, records, *, expected_count=None):
    source = root / "raw.jsonl"
    output = root / "clean.jsonl"
    duplicates = root / "duplicates.jsonl"
    stats = root / "stats.json"
    write_jsonl(source, records)
    result = clean_corpus(
        source,
        output,
        duplicates,
        stats,
        expected_count=expected_count,
    )
    saved = [json.loads(line) for line in output.read_text().splitlines()]
    dropped = [
        json.loads(line)
        for line in duplicates.read_text().splitlines()
        if line.strip()
    ]
    return result, saved, dropped, stats


class YargitayDataCleaningTests(unittest.TestCase):
    def test_removes_html_entities_script_nbsp_and_whitespace(self):
        cleaned, actions = clean_decision_text(
            '<div>İçtihat&nbsp; Metni"</div><p>Karar&nbsp;  metni</p>'
            "<script>gizli</script>"
        )
        self.assertEqual(cleaned, "İçtihat Metni\n\nKarar metni")
        self.assertEqual(actions["html_markup_removed"], 1)
        self.assertEqual(actions["html_entities_decoded"], 1)
        self.assertEqual(actions["unicode_spaces_replaced"], 2)
        self.assertEqual(actions["whitespace_normalized"], 1)
        self.assertEqual(actions["source_label_quote_removed"], 1)
        self.assertNotIn("gizli", cleaned)

        inline_cleaned, inline_actions = clean_decision_text(
            'İçtihat Metni"Adalet Bakanlığı açıklaması'
        )
        self.assertEqual(
            inline_cleaned, "İçtihat Metni\n\nAdalet Bakanlığı açıklaması"
        )
        self.assertEqual(inline_actions["source_label_quote_removed"], 1)

    def test_same_identity_keeps_longest_text_and_audits_duplicate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            short = raw_record("d-short", text='İçtihat Metni"\n\nKısa')
            long = raw_record("d-long", text='İçtihat Metni"\n\nDaha uzun karar')
            stats, saved, dropped, _ = run_clean(root, [short, long])
        self.assertEqual([record["id"] for record in saved], ["d-long"])
        self.assertEqual(dropped[0]["id"], "d-short")
        self.assertEqual(dropped[0]["duplicate_of_id"], "d-long")
        self.assertEqual(stats["identity_duplicate_groups"], 1)
        self.assertEqual(stats["identity_duplicates_removed"], 1)

    def test_same_text_for_different_decisions_is_preserved_and_flagged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = raw_record("d1", text="Aynı karar metni")
            second = raw_record(
                "d2",
                case_number="2024/3",
                decision_number="2024/4",
                text="Aynı karar metni",
            )
            stats, saved, dropped, _ = run_clean(root, [first, second])
        self.assertEqual(len(saved), 2)
        self.assertEqual(dropped, [])
        self.assertEqual(stats["exact_text_duplicate_groups_after"], 1)
        self.assertEqual(stats["output_records_in_repeated_text_groups"], 2)
        for record in saved:
            self.assertEqual(record["ayni_metin_kayit_sayisi"], 2)
            self.assertIn(
                "ayni_metin_farkli_kararlarda", record["veri_kalite_uyarilari"]
            )

    def test_missing_metadata_is_preserved_as_warning_not_invented(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = raw_record(case_number=None, decision_date=None)
            stats, saved, _, stats_path = run_clean(root, [record])
            saved_stats = json.loads(stats_path.read_text(encoding="utf-8"))
        self.assertIsNone(saved[0]["esas_no"])
        self.assertIsNone(saved[0]["karar_tarihi"])
        self.assertEqual(saved[0]["veri_kalite_durumu"], "uyarili")
        self.assertIn("eksik_esas_no", saved[0]["veri_kalite_uyarilari"])
        self.assertIn("eksik_karar_tarihi", saved[0]["veri_kalite_uyarilari"])
        self.assertEqual(stats["missing_esas_no"], 1)
        self.assertEqual(saved_stats, stats)

    def test_rejects_empty_text_invalid_json_and_count_mismatch(self):
        with self.assertRaisesRegex(DataCleaningError, "empty karar_metni"):
            clean_decision_text("   ")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "raw.jsonl"
            source.write_text('{"broken":\n', encoding="utf-8")
            with self.assertRaisesRegex(DataCleaningError, "Invalid JSON"):
                clean_corpus(
                    source,
                    root / "clean.jsonl",
                    root / "duplicates.jsonl",
                    root / "stats.json",
                )
            write_jsonl(source, [raw_record()])
            with self.assertRaisesRegex(DataCleaningError, "Record count mismatch"):
                clean_corpus(
                    source,
                    root / "clean.jsonl",
                    root / "duplicates.jsonl",
                    root / "stats.json",
                    expected_count=2,
                )

    def test_rejects_duplicate_source_id(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "raw.jsonl"
            write_jsonl(source, [raw_record(), raw_record()])
            with self.assertRaisesRegex(DataCleaningError, "Duplicate source id"):
                clean_corpus(
                    source,
                    root / "clean.jsonl",
                    root / "duplicates.jsonl",
                    root / "stats.json",
                )


if __name__ == "__main__":
    unittest.main()
