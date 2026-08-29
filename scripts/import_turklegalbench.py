"""Validate and import the TurkLegalBench corpus into the project raw schema."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, TypedDict
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from scrape_yargitay import (
    DecisionDataError,
    classify_decision_type,
    normalize_metadata_value,
)


SOURCE_NAME = "IremTRNL/TurkLegalBench"
SOURCE_URL = "https://huggingface.co/datasets/IremTRNL/TurkLegalBench"
SOURCE_DOWNLOAD_URL = f"{SOURCE_URL}/resolve/main/corpus.jsonl?download=true"
SOURCE_LICENSE = "CC BY 4.0"
SOURCE_SHA256 = "6c267d0fd9eb7d3e01c6cb10778dc636c48a0b35e43a5c4af6e1fe8981cd603e"
DECISION_NUMBER_PATTERN = re.compile(r"^\d{4}/\d+$")
YARGITAY_CHAMBER_PATTERN = re.compile(r"^\d+\. (?:Hukuk|Ceza) Dairesi$")


class ExternalCorpusError(RuntimeError):
    """Raised when the external corpus fails provenance or record validation."""


class ImportedDecision(TypedDict):
    id: str
    mahkeme: str
    daire: str
    karar_turu: str
    esas_no: str | None
    karar_no: str | None
    karar_tarihi: str | None
    baslik: str
    karar_metni: str
    metin_2000_karakter_sinirinda: bool
    kaynak: str
    kaynak_url: str
    kaynak_lisans: str
    kaynak_kayit_id: str


class ImportStats(TypedDict):
    source_sha256: str
    total_records: int
    yargitay_records: int
    unique_ids: int
    missing_esas_no: int
    missing_karar_no: int
    missing_karar_tarihi: int
    texts_at_2000_character_limit: int


def calculate_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download_source(
    destination: Path,
    *,
    expected_sha256: str = SOURCE_SHA256,
    progress_callback: Callable[[int], None] | None = None,
) -> int:
    """Download to a temporary file and publish only after hash validation."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = destination.with_suffix(destination.suffix + ".download")
    digest = hashlib.sha256()
    downloaded = 0
    next_progress = 5 * 1024 * 1024
    try:
        with urlopen(SOURCE_DOWNLOAD_URL, timeout=60) as response, temporary_path.open(
            "wb"
        ) as output:
            while block := response.read(1024 * 1024):
                output.write(block)
                digest.update(block)
                downloaded += len(block)
                if progress_callback is not None and downloaded >= next_progress:
                    progress_callback(downloaded)
                    next_progress += 5 * 1024 * 1024
    except (HTTPError, URLError, OSError) as exc:
        temporary_path.unlink(missing_ok=True)
        raise ExternalCorpusError(f"Source download failed: {exc}") from exc

    actual_sha256 = digest.hexdigest()
    if actual_sha256 != expected_sha256.casefold():
        temporary_path.unlink(missing_ok=True)
        raise ExternalCorpusError(
            f"Downloaded SHA-256 mismatch: expected {expected_sha256}, "
            f"got {actual_sha256}"
        )
    temporary_path.replace(destination)
    return downloaded


def normalize_chamber(value: Any) -> str:
    chamber = normalize_metadata_value(value, field_name="metadata.kurul")
    return re.sub(r"^(\d+)\.\s*", r"\1. ", chamber)


def is_yargitay_chamber(chamber: str) -> bool:
    return bool(
        YARGITAY_CHAMBER_PATTERN.fullmatch(chamber)
        or chamber in {"Hukuk Genel Kurulu", "Ceza Genel Kurulu"}
        or chamber.startswith("Yargıtay ")
    )


def normalize_optional_metadata(
    value: Any, *, field_name: str, pattern: re.Pattern[str] | None = None
) -> str | None:
    normalized = normalize_metadata_value(value, field_name=field_name)
    if normalized == "-":
        return None
    if pattern is not None and not pattern.fullmatch(normalized):
        raise ExternalCorpusError(f"Invalid {field_name}: {normalized}")
    return normalized


def normalize_plain_text(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ExternalCorpusError(f"Missing {field_name}")
    normalized = unicodedata.normalize("NFC", value).replace("\u0092", "\u2019")
    normalized = normalized.replace("\r\n", "\n")
    normalized = normalized.replace("\r", "\n").strip()
    if "\x00" in normalized or "\ufffd" in normalized:
        raise ExternalCorpusError(f"Invalid characters in {field_name}")
    invalid_controls = [
        character
        for character in normalized
        if unicodedata.category(character) == "Cc"
        and character not in {"\n", "\t"}
    ]
    if invalid_controls:
        raise ExternalCorpusError(f"Control characters in {field_name}")
    return normalized


def convert_record(record: dict[str, Any], *, line_number: int) -> ImportedDecision:
    if not isinstance(record, dict):
        raise ExternalCorpusError(f"Record at line {line_number} is not an object")
    metadata = record.get("metadata")
    if not isinstance(metadata, dict):
        raise ExternalCorpusError(f"Missing metadata object at line {line_number}")

    try:
        source_id = normalize_metadata_value(record.get("_id"), field_name="_id")
        title = normalize_metadata_value(record.get("title"), field_name="title")
        chamber = normalize_chamber(metadata.get("kurul"))
        text = normalize_plain_text(record.get("text"), field_name="text")
        case_number = normalize_optional_metadata(
            metadata.get("esas_no"),
            field_name="metadata.esas_no",
            pattern=DECISION_NUMBER_PATTERN,
        )
        decision_number = normalize_optional_metadata(
            metadata.get("karar_no"),
            field_name="metadata.karar_no",
            pattern=DECISION_NUMBER_PATTERN,
        )
        decision_date = normalize_optional_metadata(
            metadata.get("tarih"), field_name="metadata.tarih"
        )
    except (DecisionDataError, ValueError, TypeError) as exc:
        raise ExternalCorpusError(f"Invalid record at line {line_number}: {exc}") from exc

    if decision_date is not None:
        try:
            datetime.strptime(decision_date, "%d.%m.%Y")
        except ValueError as exc:
            raise ExternalCorpusError(
                f"Invalid metadata.tarih at line {line_number}: {decision_date}"
            ) from exc
    if not is_yargitay_chamber(chamber):
        raise ExternalCorpusError(
            f"Non-Yargitay or unknown chamber at line {line_number}: {chamber}"
        )

    return ImportedDecision(
        id=source_id,
        mahkeme="Yargıtay",
        daire=chamber,
        karar_turu=classify_decision_type(chamber),
        esas_no=case_number,
        karar_no=decision_number,
        karar_tarihi=decision_date,
        baslik=title,
        karar_metni=text,
        metin_2000_karakter_sinirinda=len(text) == 2000,
        kaynak=SOURCE_NAME,
        kaynak_url=SOURCE_URL,
        kaynak_lisans=SOURCE_LICENSE,
        kaynak_kayit_id=source_id,
    )


def import_corpus(
    input_path: Path,
    output_path: Path,
    *,
    expected_count: int | None = None,
    expected_sha256: str | None = None,
    progress_interval: int = 1000,
    progress_callback: Callable[[int], None] | None = None,
) -> ImportStats:
    if not input_path.is_file():
        raise ExternalCorpusError(f"Source corpus does not exist: {input_path}")
    source_sha256 = calculate_sha256(input_path)
    if expected_sha256 is not None and source_sha256 != expected_sha256.casefold():
        raise ExternalCorpusError(
            f"Source SHA-256 mismatch: expected {expected_sha256}, got {source_sha256}"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_suffix(output_path.suffix + ".tmp")
    seen_ids: set[str] = set()
    total_records = 0
    missing_esas_no = 0
    missing_karar_no = 0
    missing_karar_tarihi = 0
    texts_at_limit = 0

    try:
        with input_path.open("r", encoding="utf-8") as source, temporary_path.open(
            "w", encoding="utf-8", newline="\n"
        ) as destination:
            for line_number, line in enumerate(source, start=1):
                if not line.strip():
                    raise ExternalCorpusError(f"Blank JSONL record at line {line_number}")
                try:
                    raw_record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ExternalCorpusError(
                        f"Invalid JSON at line {line_number}: {exc.msg}"
                    ) from exc
                record = convert_record(raw_record, line_number=line_number)
                if record["id"] in seen_ids:
                    raise ExternalCorpusError(
                        f"Duplicate decision id at line {line_number}: {record['id']}"
                    )
                seen_ids.add(record["id"])
                total_records += 1
                missing_esas_no += record["esas_no"] is None
                missing_karar_no += record["karar_no"] is None
                missing_karar_tarihi += record["karar_tarihi"] is None
                texts_at_limit += record["metin_2000_karakter_sinirinda"]
                destination.write(json.dumps(record, ensure_ascii=False) + "\n")
                if (
                    progress_callback is not None
                    and progress_interval > 0
                    and total_records % progress_interval == 0
                ):
                    progress_callback(total_records)
    except UnicodeDecodeError as exc:
        raise ExternalCorpusError("Source corpus is not valid UTF-8") from exc
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise

    if expected_count is not None and total_records != expected_count:
        temporary_path.unlink(missing_ok=True)
        raise ExternalCorpusError(
            f"Record count mismatch: expected {expected_count}, got {total_records}"
        )
    temporary_path.replace(output_path)
    return ImportStats(
        source_sha256=source_sha256,
        total_records=total_records,
        yargitay_records=total_records,
        unique_ids=len(seen_ids),
        missing_esas_no=missing_esas_no,
        missing_karar_no=missing_karar_no,
        missing_karar_tarihi=missing_karar_tarihi,
        texts_at_2000_character_limit=texts_at_limit,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate and import the 15k TurkLegalBench Yargitay corpus."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("data/raw/yargitay_turklegalbench_source.jsonl"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/raw/yargitay_turklegalbench_15000.jsonl"),
    )
    parser.add_argument("--expected-count", type=int, default=15000)
    parser.add_argument("--expected-sha256", default=SOURCE_SHA256)
    parser.add_argument(
        "--download",
        action="store_true",
        help="Download and hash-verify corpus.jsonl before importing it.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.download:
        downloaded = download_source(
            args.input,
            expected_sha256=args.expected_sha256,
            progress_callback=lambda size: print(f"Downloaded: {size} bytes"),
        )
        print(f"Download complete: {downloaded} bytes")
    stats = import_corpus(
        args.input,
        args.output,
        expected_count=args.expected_count,
        expected_sha256=args.expected_sha256,
        progress_callback=lambda count: print(f"Validated and imported: {count}"),
    )
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
