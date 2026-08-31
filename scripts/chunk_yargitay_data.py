"""Split cleaned Yargitay decisions into boundary-aware RAG chunks."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, TypedDict


CHUNKING_VERSION = "1.0"
DEFAULT_CHUNK_SIZE = 1200
DEFAULT_OVERLAP = 200
DEFAULT_MIN_CHUNK_SIZE = 250
SENTENCE_BOUNDARY_PATTERN = re.compile(r"(?<=[.!?…])\s+")
PARAGRAPH_BOUNDARY_PATTERN = re.compile(r"\n{2,}")
COMMON_ABBREVIATIONS = {
    "av.",
    "bkz.",
    "doç.",
    "dr.",
    "e.",
    "k.",
    "mah.",
    "md.",
    "m.",
    "no.",
    "prof.",
    "s.",
    "t.c.",
    "vb.",
    "vd.",
    "vs.",
}
SECTION_MARKER_PATTERNS = {
    "ictihat_metni": re.compile(r"^\s*İçtihat Metni\s*$", re.IGNORECASE | re.MULTILINE),
    "mahkemesi": re.compile(r"^\s*MAHKEMESİ\s*:", re.IGNORECASE | re.MULTILINE),
    "dava": re.compile(
        r"^\s*(?:[IVX]+\.\s*)?DAVA(?:\s*:|\s*$)",
        re.IGNORECASE | re.MULTILINE,
    ),
    "karar": re.compile(
        r"^\s*[-_–—]?\s*(?:K\s*A\s*R\s*A\s*R|Y\s*A\s*R\s*G\s*I\s*T\s*A\s*Y\s+K\s*A\s*R\s*A\s*R\s*I|YARGITAY KARARI|(?:[IVX]+\.\s*)?KARAR)\s*[-_–—]?\s*:?[\s_]*$",
        re.IGNORECASE | re.MULTILINE,
    ),
    "sonuc": re.compile(r"^\s*SONUÇ(?:\s*:|\s*$)", re.IGNORECASE | re.MULTILINE),
    "ozet": re.compile(r"^\s*ÖZET(?:\s*:|\s*$)", re.IGNORECASE | re.MULTILINE),
    "davaci_istemi": re.compile(
        r"^\s*(?:A\)\s*)?Davacı\s+İstem(?:inin|i)?(?:\s+Özeti)?\s*:",
        re.IGNORECASE | re.MULTILINE,
    ),
    "davali_cevabi": re.compile(
        r"^\s*(?:B\)\s*)?Davalı(?:ların)?\s+Cevab(?:ının|ı)?(?:\s+Özeti)?\s*:",
        re.IGNORECASE | re.MULTILINE,
    ),
    "hukuki_surec": re.compile(
        r"^\s*(?:I\.\s*)?(?:HUKUK[İÎ]\s+SÜREÇ|YARGILAMA SÜRECİ)\s*$",
        re.IGNORECASE | re.MULTILINE,
    ),
    "cevap": re.compile(
        r"^\s*(?:II\.\s*)?CEVAP\s*$", re.IGNORECASE | re.MULTILINE
    ),
    "temyiz": re.compile(
        r"^\s*(?:(?:II|D)\.?\)?\s*)?TEMYİZ(?:\s+SEBEPLERİ)?\s*:?[\s]*$",
        re.IGNORECASE | re.MULTILINE,
    ),
    "olay_ve_olgular": re.compile(
        r"^\s*(?:III\.\s*)?OLAY VE OLGULAR\s*$",
        re.IGNORECASE | re.MULTILINE,
    ),
    "mahkeme_karari": re.compile(
        r"^\s*(?:(?:III|C)\.?\)?\s*)?(?:(?:İLK DERECE|YEREL)\s+)?MAHKEME KARAR(?:ININ|I)?(?:\s+ÖZETİ)?\s*:?[\s]*$",
        re.IGNORECASE | re.MULTILINE,
    ),
    "gerekce": re.compile(
        r"^\s*(?:(?:II|III|IV|E)\.?\)?\s*)?GEREKÇE\s*:?[\s]*$",
        re.IGNORECASE | re.MULTILINE,
    ),
    "hukum": re.compile(r"^\s*HÜKÜM(?:\s*:|\s*$)", re.IGNORECASE | re.MULTILINE),
    "inceleme": re.compile(r"^\s*İNCELEME(?:\s*:|\s*$)", re.IGNORECASE | re.MULTILINE),
    "geregi_dusunuldu": re.compile(
        r"GEREĞİ\s+(?:GÖRÜŞÜLÜP\s+)?DÜŞÜNÜLDÜ", re.IGNORECASE
    ),
    "turk_milleti_adina": re.compile(r"TÜRK MİLLETİ ADINA", re.IGNORECASE),
    "yargitay_ilami": re.compile(r"YARGITAY İLAMI", re.IGNORECASE),
    "incelenen_kararin": re.compile(r"^\s*İNCELENEN KARARIN", re.IGNORECASE | re.MULTILINE),
}


class ChunkingError(RuntimeError):
    """Raised when cleaned input cannot be chunked without hiding corruption."""


class ChunkingStats(TypedDict):
    chunking_version: str
    configuration: dict[str, int]
    input_records: int
    unique_decision_ids: int
    output_chunks: int
    unique_chunk_ids: int
    single_chunk_decisions: int
    multi_chunk_decisions: int
    chunk_count_distribution: dict[str, int]
    input_character_summary: dict[str, float | int]
    input_paragraph_summary: dict[str, float | int]
    section_marker_record_counts: dict[str, int]
    chunk_character_summary: dict[str, float | int]
    overlap_character_summary: dict[str, float | int]
    chunk_end_boundary_counts: dict[str, int]
    output_sha256: str


@dataclass(frozen=True)
class _TextSpan:
    start: int
    end: int
    boundary_kind: str


@dataclass(frozen=True)
class TextChunk:
    start: int
    end: int
    text: str
    overlap_with_previous: int
    end_boundary_kind: str
    section_markers: tuple[str, ...]


def _validate_configuration(
    chunk_size: int, overlap: int, min_chunk_size: int
) -> None:
    if chunk_size < 100:
        raise ChunkingError("chunk_size must be at least 100 characters")
    if overlap < 0 or overlap >= chunk_size:
        raise ChunkingError("overlap must be non-negative and smaller than chunk_size")
    if min_chunk_size < 1 or min_chunk_size > chunk_size:
        raise ChunkingError("min_chunk_size must be between 1 and chunk_size")


def _trim_span(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _paragraph_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    cursor = 0
    for match in PARAGRAPH_BOUNDARY_PATTERN.finditer(text):
        start, end = _trim_span(text, cursor, match.start())
        if start < end:
            spans.append((start, end))
        cursor = match.end()
    start, end = _trim_span(text, cursor, len(text))
    if start < end:
        spans.append((start, end))
    return spans


def _is_abbreviation(fragment: str) -> bool:
    words = fragment.rstrip().split()
    if not words:
        return False
    final_word = words[-1].casefold()
    if final_word in COMMON_ABBREVIATIONS:
        return True
    return bool(re.fullmatch(r"\d+\.", final_word))


def _sentence_spans(text: str, start: int, end: int) -> list[tuple[int, int]]:
    fragment = text[start:end]
    spans: list[tuple[int, int]] = []
    sentence_start = 0
    for match in SENTENCE_BOUNDARY_PATTERN.finditer(fragment):
        if _is_abbreviation(fragment[sentence_start : match.start()]):
            continue
        local_start, local_end = _trim_span(
            fragment, sentence_start, match.start()
        )
        if local_start < local_end:
            spans.append((start + local_start, start + local_end))
        sentence_start = match.end()
    local_start, local_end = _trim_span(fragment, sentence_start, len(fragment))
    if local_start < local_end:
        spans.append((start + local_start, start + local_end))
    return spans


def _split_long_span(
    text: str, start: int, end: int, max_unit_size: int
) -> list[_TextSpan]:
    spans: list[_TextSpan] = []
    cursor = start
    while end - cursor > max_unit_size:
        limit = cursor + max_unit_size
        minimum_boundary = cursor + max(1, max_unit_size // 2)
        split_at = max(
            text.rfind(" ", minimum_boundary, limit + 1),
            text.rfind("\n", minimum_boundary, limit + 1),
        )
        boundary_kind = "word"
        if split_at < minimum_boundary:
            split_at = limit
            boundary_kind = "hard"
        part_start, part_end = _trim_span(text, cursor, split_at)
        if part_start < part_end:
            spans.append(_TextSpan(part_start, part_end, boundary_kind))
        cursor = split_at
        while cursor < end and text[cursor].isspace():
            cursor += 1
    part_start, part_end = _trim_span(text, cursor, end)
    if part_start < part_end:
        spans.append(_TextSpan(part_start, part_end, "sentence"))
    return spans


def _build_atomic_spans(text: str, chunk_size: int) -> list[_TextSpan]:
    max_unit_size = max(100, chunk_size // 2)
    atomic_spans: list[_TextSpan] = []
    for paragraph_start, paragraph_end in _paragraph_spans(text):
        sentence_spans = _sentence_spans(text, paragraph_start, paragraph_end)
        for sentence_index, (sentence_start, sentence_end) in enumerate(
            sentence_spans
        ):
            is_last_sentence = sentence_index == len(sentence_spans) - 1
            if sentence_end - sentence_start > max_unit_size:
                split_spans = _split_long_span(
                    text, sentence_start, sentence_end, max_unit_size
                )
                if is_last_sentence and split_spans:
                    final = split_spans[-1]
                    split_spans[-1] = _TextSpan(
                        final.start, final.end, "paragraph"
                    )
                atomic_spans.extend(split_spans)
            else:
                atomic_spans.append(
                    _TextSpan(
                        sentence_start,
                        sentence_end,
                        "paragraph" if is_last_sentence else "sentence",
                    )
                )
    return atomic_spans


def detect_section_markers(text: str) -> tuple[str, ...]:
    return tuple(
        marker_name
        for marker_name, marker_pattern in SECTION_MARKER_PATTERNS.items()
        if marker_pattern.search(text)
    )


def chunk_text(
    text: str,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
    min_chunk_size: int = DEFAULT_MIN_CHUNK_SIZE,
) -> list[TextChunk]:
    _validate_configuration(chunk_size, overlap, min_chunk_size)
    if not isinstance(text, str) or not text.strip():
        raise ChunkingError("Decision text is empty")

    spans = _build_atomic_spans(text, chunk_size)
    if not spans:
        raise ChunkingError("Decision text has no chunkable content")

    chunks: list[TextChunk] = []
    start_index = 0
    previous_end_index = -1
    previous_chunk_end = 0
    while start_index < len(spans):
        end_index = start_index
        while (
            end_index + 1 < len(spans)
            and spans[end_index + 1].end - spans[start_index].start <= chunk_size
        ):
            end_index += 1

        if end_index <= previous_end_index:
            start_index = previous_end_index + 1
            continue

        if end_index == len(spans) - 1 and chunks:
            while (
                start_index > 0
                and spans[end_index].end - spans[start_index].start < min_chunk_size
                and spans[end_index].end - spans[start_index - 1].start <= chunk_size
            ):
                start_index -= 1

        chunk_start = spans[start_index].start
        chunk_end = spans[end_index].end
        chunk_content = text[chunk_start:chunk_end]
        if not chunk_content or len(chunk_content) > chunk_size:
            raise ChunkingError("Chunk size invariant failed")
        chunks.append(
            TextChunk(
                start=chunk_start,
                end=chunk_end,
                text=chunk_content,
                overlap_with_previous=(
                    max(0, previous_chunk_end - chunk_start) if chunks else 0
                ),
                end_boundary_kind=spans[end_index].boundary_kind,
                section_markers=detect_section_markers(chunk_content),
            )
        )
        if end_index == len(spans) - 1:
            break

        previous_end_index = end_index
        previous_chunk_end = chunk_end
        desired_start = chunk_end - overlap
        next_start_index = end_index
        for candidate in range(start_index + 1, end_index + 1):
            if spans[candidate].start >= desired_start:
                next_start_index = candidate
                break
        if next_start_index <= start_index:
            next_start_index = start_index + 1
        start_index = next_start_index

    for index, chunk in enumerate(chunks):
        if text[chunk.start : chunk.end] != chunk.text:
            raise ChunkingError("Chunk offset invariant failed")
        if index and chunk.start >= chunks[index - 1].end:
            continue
        if index and chunk.end <= chunks[index - 1].end:
            raise ChunkingError("Chunk progression invariant failed")
    return chunks


def _validate_record(raw_record: Any, line_number: int) -> dict[str, Any]:
    if not isinstance(raw_record, dict):
        raise ChunkingError(f"Record at line {line_number} is not an object")
    record = dict(raw_record)
    decision_id = record.get("id")
    text = record.get("karar_metni")
    if not isinstance(decision_id, str) or not decision_id.strip():
        raise ChunkingError(f"Missing decision id at line {line_number}")
    if not isinstance(text, str) or not text.strip():
        raise ChunkingError(f"Missing decision text at line {line_number}")
    expected_length = record.get("karar_metni_karakter_sayisi")
    if expected_length != len(text):
        raise ChunkingError(f"Decision text length mismatch at line {line_number}")
    expected_hash = record.get("karar_metni_sha256")
    actual_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if expected_hash != actual_hash:
        raise ChunkingError(f"Decision text hash mismatch at line {line_number}")
    if not isinstance(record.get("veri_kalite_uyarilari"), list):
        raise ChunkingError(f"Invalid quality warnings at line {line_number}")
    return record


def _numeric_summary(values: list[int]) -> dict[str, float | int]:
    if not values:
        return {
            "min": 0,
            "p25": 0,
            "median": 0,
            "p75": 0,
            "p90": 0,
            "p95": 0,
            "p99": 0,
            "max": 0,
            "mean": 0.0,
        }
    ordered = sorted(values)

    def percentile(fraction: float) -> int:
        return ordered[round((len(ordered) - 1) * fraction)]

    return {
        "min": ordered[0],
        "p25": percentile(0.25),
        "median": percentile(0.50),
        "p75": percentile(0.75),
        "p90": percentile(0.90),
        "p95": percentile(0.95),
        "p99": percentile(0.99),
        "max": ordered[-1],
        "mean": round(statistics.mean(ordered), 2),
    }


def chunk_corpus(
    input_path: Path,
    output_path: Path,
    stats_path: Path,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
    min_chunk_size: int = DEFAULT_MIN_CHUNK_SIZE,
    expected_count: int | None = None,
    progress_interval: int = 1000,
    progress_callback: Callable[[int], None] | None = None,
) -> ChunkingStats:
    _validate_configuration(chunk_size, overlap, min_chunk_size)
    if not input_path.is_file():
        raise ChunkingError(f"Input JSONL does not exist: {input_path}")

    records: list[dict[str, Any]] = []
    decision_ids: set[str] = set()
    try:
        with input_path.open("r", encoding="utf-8") as source:
            for line_number, line in enumerate(source, start=1):
                if not line.strip():
                    raise ChunkingError(f"Blank JSONL line at {line_number}")
                try:
                    raw_record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ChunkingError(
                        f"Invalid JSON at line {line_number}: {exc.msg}"
                    ) from exc
                record = _validate_record(raw_record, line_number)
                if record["id"] in decision_ids:
                    raise ChunkingError(
                        f"Duplicate decision id at line {line_number}: {record['id']}"
                    )
                decision_ids.add(record["id"])
                records.append(record)
    except UnicodeDecodeError as exc:
        raise ChunkingError("Input JSONL is not valid UTF-8") from exc

    if expected_count is not None and len(records) != expected_count:
        raise ChunkingError(
            f"Record count mismatch: expected {expected_count}, got {len(records)}"
        )

    output_records: list[dict[str, Any]] = []
    chunks_per_decision: list[int] = []
    input_lengths: list[int] = []
    paragraph_counts: list[int] = []
    chunk_lengths: list[int] = []
    overlap_lengths: list[int] = []
    boundary_counts: Counter[str] = Counter()
    section_record_counts: Counter[str] = Counter()
    chunk_ids: set[str] = set()

    for record_number, record in enumerate(records, start=1):
        text = record["karar_metni"]
        decision_chunks = chunk_text(
            text,
            chunk_size=chunk_size,
            overlap=overlap,
            min_chunk_size=min_chunk_size,
        )
        input_lengths.append(len(text))
        paragraph_counts.append(len(_paragraph_spans(text)))
        section_record_counts.update(detect_section_markers(text))
        chunks_per_decision.append(len(decision_chunks))
        for chunk_index, chunk in enumerate(decision_chunks, start=1):
            chunk_id = f"{record['id']}:c{chunk_index:04d}"
            if chunk_id in chunk_ids:
                raise ChunkingError(f"Duplicate chunk id generated: {chunk_id}")
            chunk_ids.add(chunk_id)
            output_record = {
                key: value
                for key, value in record.items()
                if key not in {"id", "karar_metni"}
            }
            output_record.update(
                {
                    "id": chunk_id,
                    "karar_id": record["id"],
                    "chunk_sirasi": chunk_index,
                    "toplam_chunk": len(decision_chunks),
                    "chunk_metni": chunk.text,
                    "chunk_metni_sha256": hashlib.sha256(
                        chunk.text.encode("utf-8")
                    ).hexdigest(),
                    "baslangic_karakteri": chunk.start,
                    "bitis_karakteri": chunk.end,
                    "karakter_sayisi": len(chunk.text),
                    "onceki_chunk_ortusme_karakteri": (
                        chunk.overlap_with_previous
                    ),
                    "bitis_siniri": chunk.end_boundary_kind,
                    "bolum_isaretleri": list(chunk.section_markers),
                    "chunking_surum": CHUNKING_VERSION,
                    "chunk_boyutu_karakter": chunk_size,
                    "hedef_ortusme_karakter": overlap,
                }
            )
            output_records.append(output_record)
            chunk_lengths.append(len(chunk.text))
            if chunk_index > 1:
                overlap_lengths.append(chunk.overlap_with_previous)
            boundary_counts[chunk.end_boundary_kind] += 1
        if (
            progress_callback is not None
            and progress_interval > 0
            and record_number % progress_interval == 0
        ):
            progress_callback(record_number)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    output_temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    stats_temporary = stats_path.with_suffix(stats_path.suffix + ".tmp")
    output_digest = hashlib.sha256()
    try:
        with output_temporary.open("w", encoding="utf-8", newline="\n") as stream:
            for output_record in output_records:
                encoded = (
                    json.dumps(output_record, ensure_ascii=False) + "\n"
                ).encode("utf-8")
                stream.write(encoded.decode("utf-8"))
                output_digest.update(encoded)

        distribution = Counter(chunks_per_decision)
        stats = ChunkingStats(
            chunking_version=CHUNKING_VERSION,
            configuration={
                "chunk_size": chunk_size,
                "overlap": overlap,
                "min_chunk_size": min_chunk_size,
            },
            input_records=len(records),
            unique_decision_ids=len(decision_ids),
            output_chunks=len(output_records),
            unique_chunk_ids=len(chunk_ids),
            single_chunk_decisions=distribution[1],
            multi_chunk_decisions=sum(
                count for chunk_count, count in distribution.items() if chunk_count > 1
            ),
            chunk_count_distribution={
                str(key): value for key, value in sorted(distribution.items())
            },
            input_character_summary=_numeric_summary(input_lengths),
            input_paragraph_summary=_numeric_summary(paragraph_counts),
            section_marker_record_counts={
                key: section_record_counts[key] for key in SECTION_MARKER_PATTERNS
            },
            chunk_character_summary=_numeric_summary(chunk_lengths),
            overlap_character_summary=_numeric_summary(overlap_lengths),
            chunk_end_boundary_counts=dict(sorted(boundary_counts.items())),
            output_sha256=output_digest.hexdigest(),
        )
        stats_temporary.write_text(
            json.dumps(stats, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        output_temporary.replace(output_path)
        stats_temporary.replace(stats_path)
    except Exception:
        output_temporary.unlink(missing_ok=True)
        stats_temporary.unlink(missing_ok=True)
        raise
    return stats


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create boundary-aware RAG chunks from the cleaned Yargitay corpus."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("data/processed/yargitay_clean_14870.jsonl"),
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--stats", type=Path)
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE)
    parser.add_argument("--overlap", type=int, default=DEFAULT_OVERLAP)
    parser.add_argument(
        "--min-chunk-size", type=int, default=DEFAULT_MIN_CHUNK_SIZE
    )
    parser.add_argument("--expected-count", type=int, default=14870)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = args.output or Path(
        f"data/processed/yargitay_chunks_{args.chunk_size}_{args.overlap}.jsonl"
    )
    stats_path = args.stats or Path(
        f"data/processed/yargitay_chunks_{args.chunk_size}_{args.overlap}_stats.json"
    )
    stats = chunk_corpus(
        args.input,
        output_path,
        stats_path,
        chunk_size=args.chunk_size,
        overlap=args.overlap,
        min_chunk_size=args.min_chunk_size,
        expected_count=args.expected_count,
        progress_callback=lambda count: print(f"Chunked decisions: {count}"),
    )
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
