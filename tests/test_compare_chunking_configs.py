import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from compare_chunking_configs import (
    ChunkConfiguration,
    ComparisonError,
    compare_configurations,
    parse_configuration,
    run_comparison,
    select_representative_records,
)


def decision_text(target_length):
    prefix = "İçtihat Metni\n\nMAHKEMESİ: Ankara\n\nKARAR\n\n"
    sentence = "Uyuşmazlık incelendi ve hukuki gerekçe değerlendirildi. "
    text = prefix
    while len(text) < target_length:
        text += sentence
    return text[:target_length].rstrip()


def cleaned_record(decision_id, target_length, decision_type="hukuk"):
    text = decision_text(target_length)
    return {
        "id": decision_id,
        "mahkeme": "Yargıtay",
        "daire": "1. Hukuk Dairesi" if decision_type == "hukuk" else "1. Ceza Dairesi",
        "karar_turu": decision_type,
        "esas_no": f"2024/{decision_id}",
        "karar_no": f"2025/{decision_id}",
        "karar_tarihi": "01.02.2025",
        "baslik": "Örnek karar",
        "karar_metni": text,
        "metin_2000_karakter_sinirinda": target_length >= 1900,
        "kaynak": "test",
        "kaynak_url": "https://example.test/dataset",
        "kaynak_lisans": "CC BY 4.0",
        "kaynak_kayit_id": decision_id,
        "karar_metni_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "karar_metni_karakter_sayisi": len(text),
        "ayni_metin_kayit_sayisi": 1,
        "veri_kalite_uyarilari": [],
        "veri_kalite_durumu": "gecerli",
        "temizleme_surum": "1.0",
    }


def representative_corpus(per_band=3):
    lengths = (600, 1000, 1500, 1950)
    records = []
    for band_index, length in enumerate(lengths):
        for sample_index in range(per_band):
            records.append(
                cleaned_record(
                    f"d{band_index}-{sample_index}",
                    length + sample_index,
                    "hukuk" if sample_index % 2 == 0 else "ceza",
                )
            )
    return records


def write_jsonl(path, records):
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )


class ChunkConfigurationComparisonTests(unittest.TestCase):
    def test_parses_configuration_with_optional_minimum(self):
        self.assertEqual(
            parse_configuration("1200:200"), ChunkConfiguration(1200, 200, 250)
        )
        self.assertEqual(
            parse_configuration("800/100/150"), ChunkConfiguration(800, 100, 150)
        )

    def test_selects_deterministic_samples_from_each_length_band(self):
        records = representative_corpus(per_band=4)
        first = select_representative_records(records, samples_per_band=2)
        second = select_representative_records(
            list(reversed(records)), samples_per_band=2
        )

        self.assertEqual([record["id"] for record in first], [record["id"] for record in second])
        self.assertEqual(len(first), 8)
        lengths = [len(record["karar_metni"]) for record in first]
        self.assertEqual(sum(length <= 800 for length in lengths), 2)
        self.assertEqual(sum(801 <= length <= 1200 for length in lengths), 2)
        self.assertEqual(sum(1201 <= length <= 1800 for length in lengths), 2)
        self.assertEqual(sum(length >= 1801 for length in lengths), 2)

    def test_comparison_preserves_links_and_reports_tradeoffs(self):
        records = representative_corpus(per_band=3)
        report = compare_configurations(
            records,
            (
                ChunkConfiguration(800, 100),
                ChunkConfiguration(1200, 200),
            ),
            samples_per_band=2,
        )

        self.assertTrue(report["all_integrity_checks_passed"])
        self.assertEqual(report["sampling"]["sample_records"], 8)
        self.assertEqual(len(report["results"]), 2)
        for result in report["results"]:
            self.assertTrue(result["integrity"]["passed"])
            self.assertEqual(
                result["integrity"]["uncovered_non_whitespace_characters"], 0
            )
            self.assertGreater(result["integrity"]["metadata_field_checks"], 0)
            self.assertGreater(result["output_chunks"], 0)
            self.assertGreaterEqual(result["preferred_boundary_rate_percent"], 0)
        serialized = json.dumps(report, ensure_ascii=False)
        for record in records:
            self.assertNotIn(record["karar_metni"], serialized)

    def test_each_example_contains_exact_source_link_metadata(self):
        records = representative_corpus(per_band=2)
        report = compare_configurations(
            records,
            (ChunkConfiguration(800, 100),),
            samples_per_band=1,
        )
        by_id = {record["id"]: record for record in records}

        for sample in report["samples"]:
            source = by_id[sample["karar_id"]]
            self.assertEqual(sample["daire"], source["daire"])
            self.assertEqual(sample["esas_no"], source["esas_no"])
            self.assertEqual(sample["karar_no"], source["karar_no"])
            self.assertEqual(sample["karar_tarihi"], source["karar_tarihi"])
            self.assertEqual(
                sample["karar_metni_sha256"], source["karar_metni_sha256"]
            )
            chunks = sample["yapilandirma_sonuclari"]["800_100"]["chunklar"]
            self.assertEqual([chunk["id"] for chunk in chunks], [
                f"{source['id']}:c{index:04d}" for index in range(1, len(chunks) + 1)
            ])

    def test_run_comparison_writes_atomic_reproducible_report(self):
        records = representative_corpus(per_band=2)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "clean.jsonl"
            output = root / "comparison.json"
            write_jsonl(source, records)
            source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
            report = run_comparison(
                source,
                output,
                (ChunkConfiguration(800, 100),),
                samples_per_band=1,
                expected_count=len(records),
            )
            saved = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(saved, report)
        self.assertEqual(report["input"]["sha256"], source_hash)
        self.assertTrue(report["all_integrity_checks_passed"])

    def test_rejects_duplicate_configuration_keys_and_missing_band(self):
        records = representative_corpus(per_band=1)
        with self.assertRaises(ComparisonError):
            compare_configurations(
                records,
                (
                    ChunkConfiguration(800, 100, 200),
                    ChunkConfiguration(800, 100, 250),
                ),
                samples_per_band=1,
            )
        with self.assertRaises(ComparisonError):
            select_representative_records(records[:-1], samples_per_band=1)


if __name__ == "__main__":
    unittest.main()
