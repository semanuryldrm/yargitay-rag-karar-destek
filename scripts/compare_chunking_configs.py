"""Compare boundary-aware chunk sizes and overlaps on representative decisions."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from chunk_yargitay_data import (
    ChunkingError,
    chunk_decision_record,
    detect_section_markers,
    load_cleaned_records,
)


COMPARISON_VERSION = "1.0"
DEFAULT_SAMPLES_PER_BAND = 6
DEFAULT_MIN_CHUNK_SIZE = 250
LENGTH_BANDS = (
    ("kisa", 0, 800),
    ("orta", 801, 1200),
    ("uzun", 1201, 1800),
    ("cok_uzun", 1801, None),
)
SOURCE_LINK_FIELDS = (
    "daire",
    "esas_no",
    "karar_no",
    "karar_tarihi",
    "karar_metni_sha256",
    "kaynak",
    "kaynak_url",
    "kaynak_lisans",
    "kaynak_kayit_id",
)


class ComparisonError(RuntimeError):
    """Raised when a comparison cannot be completed without hiding bad data."""


@dataclass(frozen=True, order=True)
class ChunkConfiguration:
    chunk_size: int
    overlap: int
    min_chunk_size: int = DEFAULT_MIN_CHUNK_SIZE

    @property
    def key(self) -> str:
        return f"{self.chunk_size}_{self.overlap}"


DEFAULT_CONFIGURATIONS = tuple(
    ChunkConfiguration(chunk_size, overlap)
    for chunk_size in (800, 1200, 1600)
    for overlap in (100, 200, 300)
)


def parse_configuration(value: str) -> ChunkConfiguration:
    """Parse SIZE:OVERLAP[:MIN_SIZE] command-line configuration syntax."""
    parts = value.replace("/", ":").split(":")
    if len(parts) not in {2, 3}:
        raise argparse.ArgumentTypeError(
            "configuration must be SIZE:OVERLAP or SIZE:OVERLAP:MIN_SIZE"
        )
    try:
        values = [int(part) for part in parts]
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "configuration values must be integers"
        ) from exc
    configuration = ChunkConfiguration(
        values[0],
        values[1],
        values[2] if len(values) == 3 else DEFAULT_MIN_CHUNK_SIZE,
    )
    try:
        _validate_configurations((configuration,))
    except ComparisonError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    return configuration


def _validate_configurations(
    configurations: Iterable[ChunkConfiguration],
) -> tuple[ChunkConfiguration, ...]:
    validated = tuple(configurations)
    if not validated:
        raise ComparisonError("At least one chunk configuration is required")
    keys: set[str] = set()
    for configuration in validated:
        if configuration.chunk_size < 100:
            raise ComparisonError("chunk_size must be at least 100 characters")
        if configuration.overlap < 0 or configuration.overlap >= configuration.chunk_size:
            raise ComparisonError(
                "overlap must be non-negative and smaller than chunk_size"
            )
        if not 1 <= configuration.min_chunk_size <= configuration.chunk_size:
            raise ComparisonError(
                "min_chunk_size must be between 1 and chunk_size"
            )
        if configuration.key in keys:
            raise ComparisonError(
                f"Duplicate chunk configuration key: {configuration.key}"
            )
        keys.add(configuration.key)
    return validated


def _length_band(character_count: int) -> str:
    for name, minimum, maximum in LENGTH_BANDS:
        if character_count >= minimum and (
            maximum is None or character_count <= maximum
        ):
            return name
    raise ComparisonError(f"No length band for {character_count} characters")


def _stable_record_key(record: dict[str, Any]) -> str:
    source = f"{record['id']}|{record['karar_metni_sha256']}"
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _round_robin_by_decision_type(
    records: list[dict[str, Any]], count: int
) -> list[dict[str, Any]]:
    pools: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        decision_type = str(record.get("karar_turu") or "bilinmiyor").casefold()
        pools[decision_type].append(record)
    for pool in pools.values():
        pool.sort(key=_stable_record_key)

    selected: list[dict[str, Any]] = []
    decision_types = sorted(pools)
    while len(selected) < count:
        made_progress = False
        for decision_type in decision_types:
            if pools[decision_type]:
                selected.append(pools[decision_type].pop(0))
                made_progress = True
                if len(selected) == count:
                    break
        if not made_progress:
            break
    return selected


def select_representative_records(
    records: list[dict[str, Any]], *, samples_per_band: int
) -> list[dict[str, Any]]:
    """Select stable, length-stratified samples with decision-type diversity."""
    if samples_per_band < 1:
        raise ComparisonError("samples_per_band must be positive")

    by_band: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_band[_length_band(len(record["karar_metni"]))].append(record)

    selected: list[dict[str, Any]] = []
    for band_name, _, _ in LENGTH_BANDS:
        candidates = by_band[band_name]
        if len(candidates) < samples_per_band:
            raise ComparisonError(
                f"Length band {band_name!r} has {len(candidates)} records; "
                f"{samples_per_band} required"
            )
        selected.extend(
            _round_robin_by_decision_type(candidates, samples_per_band)
        )
    return selected


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


def _preview(text: str, limit: int = 120) -> str:
    compact = " ".join(text.split())
    return compact if len(compact) <= limit else compact[: limit - 1] + "…"


def _validate_decision_chunks(
    source_record: dict[str, Any],
    chunks: list[dict[str, Any]],
    configuration: ChunkConfiguration,
) -> dict[str, int]:
    decision_id = source_record["id"]
    source_text = source_record["karar_metni"]
    if not chunks:
        raise ComparisonError(f"No chunks generated for decision {decision_id}")

    coverage = [0] * len(source_text)
    source_metadata = {
        key: value
        for key, value in source_record.items()
        if key not in {"id", "karar_metni"}
    }
    previous_end = -1
    union_markers: set[str] = set()
    metadata_checks = 0
    for index, chunk in enumerate(chunks, start=1):
        expected_id = f"{decision_id}:c{index:04d}"
        if chunk.get("id") != expected_id:
            raise ComparisonError(
                f"Chunk id mismatch for {decision_id}: {chunk.get('id')!r}"
            )
        if chunk.get("karar_id") != decision_id:
            raise ComparisonError(f"Source id link mismatch for {expected_id}")
        if chunk.get("chunk_sirasi") != index or chunk.get("toplam_chunk") != len(chunks):
            raise ComparisonError(f"Chunk sequence mismatch for {expected_id}")
        if chunk.get("chunk_boyutu_karakter") != configuration.chunk_size:
            raise ComparisonError(f"Chunk size metadata mismatch for {expected_id}")
        if chunk.get("hedef_ortusme_karakter") != configuration.overlap:
            raise ComparisonError(f"Overlap metadata mismatch for {expected_id}")

        start = chunk.get("baslangic_karakteri")
        end = chunk.get("bitis_karakteri")
        if not isinstance(start, int) or not isinstance(end, int) or not 0 <= start < end <= len(source_text):
            raise ComparisonError(f"Invalid source offsets for {expected_id}")
        if end <= previous_end:
            raise ComparisonError(f"Chunk end did not advance for {expected_id}")
        previous_end = end
        chunk_text = chunk.get("chunk_metni")
        if source_text[start:end] != chunk_text:
            raise ComparisonError(f"Source text link mismatch for {expected_id}")
        if chunk.get("karakter_sayisi") != len(chunk_text):
            raise ComparisonError(f"Chunk length mismatch for {expected_id}")
        actual_hash = hashlib.sha256(chunk_text.encode("utf-8")).hexdigest()
        if chunk.get("chunk_metni_sha256") != actual_hash:
            raise ComparisonError(f"Chunk hash mismatch for {expected_id}")
        for position in range(start, end):
            coverage[position] += 1

        for key, value in source_metadata.items():
            metadata_checks += 1
            if chunk.get(key) != value:
                raise ComparisonError(
                    f"Metadata field {key!r} changed in {expected_id}"
                )
        for required_field in SOURCE_LINK_FIELDS:
            if required_field not in chunk:
                raise ComparisonError(
                    f"Required source link field {required_field!r} missing in {expected_id}"
                )
        union_markers.update(chunk.get("bolum_isaretleri", []))

    uncovered_non_whitespace = sum(
        1
        for position, character in enumerate(source_text)
        if not character.isspace() and coverage[position] == 0
    )
    if uncovered_non_whitespace:
        raise ComparisonError(
            f"{uncovered_non_whitespace} source characters were not covered for {decision_id}"
        )
    expected_markers = set(detect_section_markers(source_text))
    if union_markers != expected_markers:
        raise ComparisonError(f"Section marker link mismatch for {decision_id}")

    return {
        "metadata_checks": metadata_checks,
        "covered_source_characters": sum(1 for count in coverage if count > 0),
        "duplicate_coverage_characters": sum(
            max(0, count - 1) for count in coverage
        ),
        "uncovered_non_whitespace_characters": uncovered_non_whitespace,
    }


def evaluate_configuration(
    records: list[dict[str, Any]], configuration: ChunkConfiguration
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Evaluate one configuration and return aggregate and per-example metrics."""
    try:
        _validate_configurations((configuration,))
    except ComparisonError:
        raise

    chunk_lengths: list[int] = []
    overlap_lengths: list[int] = []
    chunks_per_decision: list[int] = []
    boundary_counts: Counter[str] = Counter()
    total_covered_characters = 0
    total_duplicate_characters = 0
    metadata_checks = 0
    sample_results: dict[str, dict[str, Any]] = {}

    for record in records:
        try:
            chunks = chunk_decision_record(
                record,
                chunk_size=configuration.chunk_size,
                overlap=configuration.overlap,
                min_chunk_size=configuration.min_chunk_size,
            )
        except ChunkingError as exc:
            raise ComparisonError(
                f"Chunking failed for {record.get('id')}: {exc}"
            ) from exc

        integrity = _validate_decision_chunks(record, chunks, configuration)
        metadata_checks += integrity["metadata_checks"]
        total_covered_characters += integrity["covered_source_characters"]
        total_duplicate_characters += integrity["duplicate_coverage_characters"]
        chunks_per_decision.append(len(chunks))
        chunk_lengths.extend(chunk["karakter_sayisi"] for chunk in chunks)
        overlap_lengths.extend(
            chunk["onceki_chunk_ortusme_karakteri"] for chunk in chunks[1:]
        )
        boundary_counts.update(chunk["bitis_siniri"] for chunk in chunks)
        sample_results[record["id"]] = {
            "chunk_sayisi": len(chunks),
            "chunklar": [
                {
                    "id": chunk["id"],
                    "baslangic_karakteri": chunk["baslangic_karakteri"],
                    "bitis_karakteri": chunk["bitis_karakteri"],
                    "karakter_sayisi": chunk["karakter_sayisi"],
                    "onceki_chunk_ortusme_karakteri": chunk[
                        "onceki_chunk_ortusme_karakteri"
                    ],
                    "bitis_siniri": chunk["bitis_siniri"],
                    "bolum_isaretleri": chunk["bolum_isaretleri"],
                    "onizleme": _preview(chunk["chunk_metni"]),
                }
                for chunk in chunks
            ],
        }

    total_chunks = len(chunk_lengths)
    preferred_boundaries = (
        boundary_counts["paragraph"] + boundary_counts["sentence"]
    )
    result = {
        "configuration": asdict(configuration),
        "configuration_key": configuration.key,
        "sample_decisions": len(records),
        "output_chunks": total_chunks,
        "single_chunk_decisions": sum(
            1 for chunk_count in chunks_per_decision if chunk_count == 1
        ),
        "multi_chunk_decisions": sum(
            1 for chunk_count in chunks_per_decision if chunk_count > 1
        ),
        "average_chunks_per_decision": round(
            statistics.mean(chunks_per_decision), 2
        ),
        "chunks_per_decision_summary": _numeric_summary(chunks_per_decision),
        "chunk_character_summary": _numeric_summary(chunk_lengths),
        "overlap_character_summary": _numeric_summary(overlap_lengths),
        "chunk_end_boundary_counts": dict(sorted(boundary_counts.items())),
        "preferred_boundary_rate_percent": round(
            preferred_boundaries * 100 / total_chunks, 2
        ),
        "total_chunk_characters": sum(chunk_lengths),
        "covered_source_characters": total_covered_characters,
        "duplicate_coverage_characters": total_duplicate_characters,
        "duplicate_coverage_rate_percent": round(
            total_duplicate_characters * 100 / total_covered_characters, 2
        ),
        "integrity": {
            "passed": True,
            "metadata_field_checks": metadata_checks,
            "uncovered_non_whitespace_characters": 0,
            "offset_text_hash_sequence_and_section_checks": "passed",
        },
    }
    return result, sample_results


def compare_configurations(
    records: list[dict[str, Any]],
    configurations: Iterable[ChunkConfiguration],
    *,
    samples_per_band: int = DEFAULT_SAMPLES_PER_BAND,
) -> dict[str, Any]:
    """Create a deterministic comparison report without duplicating source texts."""
    validated_configurations = _validate_configurations(configurations)
    samples = select_representative_records(
        records, samples_per_band=samples_per_band
    )
    sample_details: dict[str, dict[str, Any]] = {}
    for record in samples:
        sample_details[record["id"]] = {
            "karar_id": record["id"],
            "uzunluk_grubu": _length_band(len(record["karar_metni"])),
            "karakter_sayisi": len(record["karar_metni"]),
            "karar_turu": record.get("karar_turu"),
            "daire": record.get("daire"),
            "esas_no": record.get("esas_no"),
            "karar_no": record.get("karar_no"),
            "karar_tarihi": record.get("karar_tarihi"),
            "karar_metni_sha256": record["karar_metni_sha256"],
            "bolum_isaretleri": list(
                detect_section_markers(record["karar_metni"])
            ),
            "yapilandirma_sonuclari": {},
        }

    aggregate_results: list[dict[str, Any]] = []
    for configuration in validated_configurations:
        aggregate, per_sample = evaluate_configuration(samples, configuration)
        aggregate_results.append(aggregate)
        for decision_id, result in per_sample.items():
            sample_details[decision_id]["yapilandirma_sonuclari"][
                configuration.key
            ] = result

    return {
        "comparison_version": COMPARISON_VERSION,
        "sampling": {
            "method": "length_stratified_and_decision_type_round_robin",
            "samples_per_length_band": samples_per_band,
            "sample_records": len(samples),
            "length_bands": [
                {"name": name, "minimum": minimum, "maximum": maximum}
                for name, minimum, maximum in LENGTH_BANDS
            ],
            "length_band_counts": dict(
                sorted(
                    Counter(
                        _length_band(len(record["karar_metni"]))
                        for record in samples
                    ).items()
                )
            ),
            "decision_type_counts": dict(
                sorted(
                    Counter(
                        str(record.get("karar_turu") or "bilinmiyor")
                        for record in samples
                    ).items()
                )
            ),
            "source_truncation_warning_records": sum(
                bool(record.get("metin_2000_karakter_sinirinda"))
                for record in samples
            ),
        },
        "configurations": [
            {**asdict(configuration), "key": configuration.key}
            for configuration in validated_configurations
        ],
        "results": aggregate_results,
        "all_integrity_checks_passed": all(
            result["integrity"]["passed"] for result in aggregate_results
        ),
        "samples": list(sample_details.values()),
    }


def run_comparison(
    input_path: Path,
    output_path: Path,
    configurations: Iterable[ChunkConfiguration] = DEFAULT_CONFIGURATIONS,
    *,
    samples_per_band: int = DEFAULT_SAMPLES_PER_BAND,
    expected_count: int | None = None,
) -> dict[str, Any]:
    records = load_cleaned_records(input_path, expected_count=expected_count)
    report = compare_configurations(
        records,
        configurations,
        samples_per_band=samples_per_band,
    )
    report["input"] = {
        "path": input_path.as_posix(),
        "records": len(records),
        "sha256": hashlib.sha256(input_path.read_bytes()).hexdigest(),
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_suffix(output_path.suffix + ".tmp")
    try:
        temporary_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(output_path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare chunk sizes and overlaps on deterministic, representative "
            "Yargitay decision samples."
        )
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("data/processed/yargitay_clean_14870.jsonl"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "data/processed/yargitay_chunk_config_comparison_stats.json"
        ),
    )
    parser.add_argument(
        "--config",
        action="append",
        type=parse_configuration,
        help="SIZE:OVERLAP[:MIN_SIZE]; repeat for multiple configurations",
    )
    parser.add_argument(
        "--samples-per-band", type=int, default=DEFAULT_SAMPLES_PER_BAND
    )
    parser.add_argument("--expected-count", type=int, default=14870)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = run_comparison(
        args.input,
        args.output,
        args.config or DEFAULT_CONFIGURATIONS,
        samples_per_band=args.samples_per_band,
        expected_count=args.expected_count,
    )
    compact_results = [
        {
            "configuration": result["configuration_key"],
            "chunks": result["output_chunks"],
            "average_chunks_per_decision": result[
                "average_chunks_per_decision"
            ],
            "median_chunk_characters": result["chunk_character_summary"][
                "median"
            ],
            "preferred_boundary_rate_percent": result[
                "preferred_boundary_rate_percent"
            ],
            "duplicate_coverage_rate_percent": result[
                "duplicate_coverage_rate_percent"
            ],
        }
        for result in report["results"]
    ]
    print(json.dumps(compact_results, ensure_ascii=False, indent=2))
    print(f"Comparison report: {args.output}")


if __name__ == "__main__":
    main()
