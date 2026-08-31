import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from chunk_yargitay_data import (
    ChunkingError,
    chunk_corpus,
    chunk_text,
    detect_section_markers,
)


def cleaned_record(decision_id="d1", text="Kısa karar metni."):
    return {
        "id": decision_id,
        "mahkeme": "Yargıtay",
        "daire": "1. Hukuk Dairesi",
        "karar_turu": "hukuk",
        "esas_no": "2024/1",
        "karar_no": "2024/2",
        "karar_tarihi": "01.02.2024",
        "baslik": "Örnek karar",
        "karar_metni": text,
        "metin_2000_karakter_sinirinda": False,
        "kaynak": "test",
        "kaynak_url": "https://example.test",
        "kaynak_lisans": "CC BY 4.0",
        "kaynak_kayit_id": decision_id,
        "karar_metni_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "karar_metni_karakter_sayisi": len(text),
        "ayni_metin_kayit_sayisi": 1,
        "veri_kalite_uyarilari": [],
        "veri_kalite_durumu": "gecerli",
        "temizleme_surum": "1.0",
    }


def write_jsonl(path, records):
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )


class YargitayChunkingTests(unittest.TestCase):
    def test_short_text_stays_in_one_exact_chunk(self):
        text = "İçtihat Metni\n\nKısa karar metni."
        chunks = chunk_text(text, chunk_size=120, overlap=20, min_chunk_size=20)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].text, text)
        self.assertEqual(chunks[0].start, 0)
        self.assertEqual(chunks[0].end, len(text))
        self.assertEqual(chunks[0].overlap_with_previous, 0)

    def test_prefers_paragraph_and_sentence_boundaries_with_overlap(self):
        text = (
            "ÖZET\n\nBirinci cümle kararın olayını açıklar. "
            "İkinci cümle hukuki değerlendirmeyi açıklar.\n\n"
            "KARAR\n\nÜçüncü cümle sonucu açıklar. "
            "Dördüncü cümle hükmü tamamlar."
        )
        chunks = chunk_text(text, chunk_size=110, overlap=25, min_chunk_size=20)
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertLessEqual(len(chunk.text), 110)
            self.assertEqual(text[chunk.start : chunk.end], chunk.text)
            self.assertFalse(chunk.text.startswith(" "))
            self.assertFalse(chunk.text.endswith(" "))
        covered = [False] * len(text)
        for chunk in chunks:
            for position in range(chunk.start, chunk.end):
                covered[position] = True
        self.assertTrue(
            all(character.isspace() or covered[index] for index, character in enumerate(text))
        )
        self.assertGreater(chunks[1].overlap_with_previous, 0)
        self.assertIn(chunks[0].end_boundary_kind, {"paragraph", "sentence"})

    def test_long_sentence_falls_back_to_word_and_hard_boundaries(self):
        spaced = " ".join(["kelime"] * 80)
        spaced_chunks = chunk_text(
            spaced, chunk_size=120, overlap=20, min_chunk_size=20
        )
        self.assertTrue(
            any(chunk.end_boundary_kind == "word" for chunk in spaced_chunks)
        )
        self.assertTrue(all(len(chunk.text) <= 120 for chunk in spaced_chunks))

        unbroken = "a" * 350
        hard_chunks = chunk_text(
            unbroken, chunk_size=120, overlap=20, min_chunk_size=20
        )
        self.assertTrue(
            any(chunk.end_boundary_kind == "hard" for chunk in hard_chunks)
        )
        self.assertTrue(all(len(chunk.text) <= 120 for chunk in hard_chunks))

    def test_detects_common_legal_section_markers(self):
        markers = detect_section_markers(
            "İçtihat Metni\n\nMAHKEMESİ: Ankara\n\nÖZET\n\nKARAR\n\nSONUÇ"
        )
        self.assertEqual(
            markers,
            ("ictihat_metni", "mahkemesi", "karar", "sonuc", "ozet"),
        )

    def test_corpus_output_preserves_metadata_offsets_and_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "clean.jsonl"
            output = root / "chunks.jsonl"
            stats_path = root / "stats.json"
            text = "ÖZET\n\n" + " ".join(["karar"] * 80) + "\n\nSONUÇ"
            write_jsonl(source, [cleaned_record("d1", text)])
            stats = chunk_corpus(
                source,
                output,
                stats_path,
                chunk_size=120,
                overlap=20,
                min_chunk_size=20,
                expected_count=1,
            )
            saved = [
                json.loads(line)
                for line in output.read_text(encoding="utf-8").splitlines()
            ]
            output_hash = hashlib.sha256(output.read_bytes()).hexdigest()

        self.assertGreater(len(saved), 1)
        self.assertEqual(stats["output_chunks"], len(saved))
        self.assertEqual(stats["unique_chunk_ids"], len(saved))
        self.assertEqual([item["chunk_sirasi"] for item in saved], list(range(1, len(saved) + 1)))
        for item in saved:
            self.assertEqual(item["karar_id"], "d1")
            self.assertEqual(item["toplam_chunk"], len(saved))
            self.assertEqual(
                text[item["baslangic_karakteri"] : item["bitis_karakteri"]],
                item["chunk_metni"],
            )
            self.assertEqual(item["karakter_sayisi"], len(item["chunk_metni"]))
            self.assertEqual(
                item["chunk_metni_sha256"],
                hashlib.sha256(item["chunk_metni"].encode("utf-8")).hexdigest(),
            )
        self.assertEqual(output_hash, stats["output_sha256"])

    def test_rejects_invalid_configuration_and_empty_text(self):
        with self.assertRaises(ChunkingError):
            chunk_text("metin", chunk_size=100, overlap=100, min_chunk_size=10)
        with self.assertRaises(ChunkingError):
            chunk_text("", chunk_size=100, overlap=10, min_chunk_size=10)
        with self.assertRaises(ChunkingError):
            chunk_text("metin", chunk_size=100, overlap=10, min_chunk_size=101)

    def test_rejects_corrupt_input_before_publishing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "clean.jsonl"
            output = root / "chunks.jsonl"
            stats_path = root / "stats.json"
            bad = cleaned_record("d1", "karar metni")
            bad["karar_metni_sha256"] = "yanlis"
            write_jsonl(source, [bad])
            with self.assertRaises(ChunkingError):
                chunk_corpus(source, output, stats_path, expected_count=1)
            self.assertFalse(output.exists())
            self.assertFalse(stats_path.exists())


if __name__ == "__main__":
    unittest.main()
