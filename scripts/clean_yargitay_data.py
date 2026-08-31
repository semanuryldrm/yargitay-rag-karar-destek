"""Clean, deduplicate, and quality-label the imported Yargitay corpus."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import unicodedata
from collections import Counter, defaultdict
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, TypedDict


CLEANING_VERSION = "1.0"
BLOCK_TAGS = {
    "address",
    "article",
    "blockquote",
    "br",
    "div",
    "footer",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "hr",
    "li",
    "main",
    "ol",
    "p",
    "section",
    "table",
    "td",
    "th",
    "tr",
    "ul",
}
IGNORED_TAGS = {"script", "style"}
HTML_TAG_PATTERN = re.compile(r"<\s*/?\s*[A-Za-z][^>]*>")
HORIZONTAL_SPACE_PATTERN = re.compile(r"[ \t\f\v]+")
EXCESS_BLANK_LINES_PATTERN = re.compile(r"\n{3,}")
SOURCE_LABEL_QUOTE_PATTERN = re.compile(r'^İçtihat Metni"')
UNICODE_SPACES = {"\u00a0", "\u2007", "\u202f"}
ZERO_WIDTH_CHARACTERS = {"\u200b", "\u200c", "\u200d", "\ufeff"}
REQUIRED_STRING_FIELDS = (
    "id",
    "mahkeme",
    "daire",
    "karar_turu",
    "baslik",
    "kaynak",
    "kaynak_url",
    "kaynak_lisans",
    "kaynak_kayit_id",
)


class DataCleaningError(RuntimeError):
    """Raised when raw data cannot be cleaned without hiding corruption."""


class CleaningStats(TypedDict):
    cleaning_version: str
    input_records: int
    output_records: int
    unique_output_ids: int
    identity_duplicate_groups: int
    identity_duplicates_removed: int
    exact_text_duplicate_groups_before: int
    exact_text_duplicate_groups_after: int
    output_records_in_repeated_text_groups: int
    records_with_cleaning_changes: int
    line_ending_records_normalized: int
    html_markup_records_cleaned: int
    html_entity_records_decoded: int
    unicode_space_records_cleaned: int
    unicode_space_characters_replaced: int
    zero_width_records_cleaned: int
    unicode_nfc_records_normalized: int
    whitespace_records_normalized: int
    source_label_quote_records_cleaned: int
    missing_esas_no: int
    missing_karar_no: int
    missing_karar_tarihi: int
    source_texts_at_2000_character_limit: int
    quality_warning_records: int
    warning_counts: dict[str, int]
    output_sha256: str


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.ignored_depth = 0

    def _append_break(self) -> None:
        if not self.parts:
            return
        trailing_newlines = len(self.parts[-1]) - len(self.parts[-1].rstrip("\n"))
        if trailing_newlines < 2:
            self.parts.append("\n" * (2 - trailing_newlines))

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        del attrs
        normalized = tag.casefold()
        if normalized in IGNORED_TAGS:
            self.ignored_depth += 1
        elif not self.ignored_depth and normalized in BLOCK_TAGS:
            self._append_break()

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        del attrs
        if not self.ignored_depth and tag.casefold() in BLOCK_TAGS:
            self._append_break()

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.casefold()
        if normalized in IGNORED_TAGS:
            if self.ignored_depth:
                self.ignored_depth -= 1
        elif not self.ignored_depth and normalized in BLOCK_TAGS:
            self._append_break()

    def handle_data(self, data: str) -> None:
        if not self.ignored_depth:
            self.parts.append(data)


def _normalize_required_string(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise DataCleaningError(f"Missing or non-string field: {field_name}")
    normalized = unicodedata.normalize("NFC", value).replace("\u00a0", " ")
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if not normalized:
        raise DataCleaningError(f"Missing or empty field: {field_name}")
    if "\x00" in normalized or "\ufffd" in normalized:
        raise DataCleaningError(f"Invalid characters in field: {field_name}")
    return normalized


def clean_decision_text(value: Any) -> tuple[str, Counter[str]]:
    if not isinstance(value, str) or not value.strip():
        raise DataCleaningError("Decision record has an empty karar_metni")

    actions: Counter[str] = Counter()
    text = value.replace("\r\n", "\n").replace("\r", "\n")
    if text != value:
        actions["line_endings_normalized"] = 1
    decoded = html.unescape(text)
    if decoded != text:
        actions["html_entities_decoded"] = 1
    if HTML_TAG_PATTERN.search(text):
        parser = _HTMLTextExtractor()
        try:
            parser.feed(text)
            parser.close()
        except (UnicodeError, ValueError) as exc:
            raise DataCleaningError("Malformed HTML in karar_metni") from exc
        text = "".join(parser.parts)
        actions["html_markup_removed"] = 1
    else:
        text = decoded

    unicode_space_count = sum(text.count(character) for character in UNICODE_SPACES)
    if unicode_space_count:
        actions["unicode_spaces_replaced"] = unicode_space_count
        for character in UNICODE_SPACES:
            text = text.replace(character, " ")

    zero_width_count = sum(
        text.count(character) for character in ZERO_WIDTH_CHARACTERS
    )
    if zero_width_count:
        actions["zero_width_characters_removed"] = zero_width_count
        for character in ZERO_WIDTH_CHARACTERS:
            text = text.replace(character, "")

    nfc_text = unicodedata.normalize("NFC", text)
    if nfc_text != text:
        actions["unicode_nfc_normalized"] = 1
    text = nfc_text
    before_whitespace_normalization = text
    normalized_lines = [
        HORIZONTAL_SPACE_PATTERN.sub(" ", line).strip() for line in text.split("\n")
    ]
    text = "\n".join(normalized_lines).strip()
    text = EXCESS_BLANK_LINES_PATTERN.sub("\n\n", text)
    if text != before_whitespace_normalization:
        actions["whitespace_normalized"] = 1
    if SOURCE_LABEL_QUOTE_PATTERN.search(text):
        replacement = "İçtihat Metni"
        artifact_length = len('İçtihat Metni"')
        if len(text) > artifact_length and text[artifact_length] != "\n":
            replacement += "\n\n"
        text = SOURCE_LABEL_QUOTE_PATTERN.sub(replacement, text, count=1)
        actions["source_label_quote_removed"] = 1

    if not text:
        raise DataCleaningError("Decision text became empty after cleaning")
    if "\x00" in text or "\ufffd" in text:
        raise DataCleaningError("Invalid characters remain in karar_metni")
    invalid_controls = [
        character
        for character in text
        if unicodedata.category(character) == "Cc" and character != "\n"
    ]
    if invalid_controls:
        raise DataCleaningError("Unsupported control characters in karar_metni")
    return text, actions


def _validate_and_clean_record(
    raw_record: Any, *, line_number: int
) -> tuple[dict[str, Any], Counter[str]]:
    if not isinstance(raw_record, dict):
        raise DataCleaningError(f"Record at line {line_number} is not an object")

    record = dict(raw_record)
    for field_name in REQUIRED_STRING_FIELDS:
        record[field_name] = _normalize_required_string(
            record.get(field_name), field_name=field_name
        )
    if record["mahkeme"] != "Yargıtay":
        raise DataCleaningError(
            f"Unexpected mahkeme at line {line_number}: {record['mahkeme']}"
        )
    if record["karar_turu"] not in {"hukuk", "ceza", "kurul", "diger"}:
        raise DataCleaningError(
            f"Unexpected karar_turu at line {line_number}: {record['karar_turu']}"
        )
    for optional_field in ("esas_no", "karar_no", "karar_tarihi"):
        value = record.get(optional_field)
        if value is not None:
            record[optional_field] = _normalize_required_string(
                value, field_name=optional_field
            )
    source_limit = record.get("metin_2000_karakter_sinirinda")
    if not isinstance(source_limit, bool):
        raise DataCleaningError(
            f"Invalid metin_2000_karakter_sinirinda at line {line_number}"
        )

    cleaned_text, actions = clean_decision_text(record.get("karar_metni"))
    record["karar_metni"] = cleaned_text
    return record, actions


def _decision_identity(record: dict[str, Any]) -> tuple[str, str, str] | None:
    values = (record["daire"], record.get("esas_no"), record.get("karar_no"))
    if any(value is None for value in values):
        return None
    return values  # type: ignore[return-value]


def _count_duplicate_text_groups(records: list[dict[str, Any]]) -> tuple[int, int]:
    groups: Counter[str] = Counter(
        hashlib.sha256(record["karar_metni"].encode("utf-8")).hexdigest()
        for record in records
    )
    duplicates = [count for count in groups.values() if count > 1]
    return len(duplicates), sum(duplicates)


def clean_corpus(
    input_path: Path,
    output_path: Path,
    duplicates_path: Path,
    stats_path: Path,
    *,
    expected_count: int | None = None,
    progress_interval: int = 1000,
    progress_callback: Callable[[int], None] | None = None,
) -> CleaningStats:
    if not input_path.is_file():
        raise DataCleaningError(f"Input JSONL does not exist: {input_path}")

    entries: list[tuple[int, dict[str, Any]]] = []
    seen_ids: set[str] = set()
    action_totals: Counter[str] = Counter()
    action_records: Counter[str] = Counter()
    records_with_changes = 0
    try:
        with input_path.open("r", encoding="utf-8") as source:
            for line_number, line in enumerate(source, start=1):
                if not line.strip():
                    raise DataCleaningError(f"Blank JSONL line at {line_number}")
                try:
                    raw_record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise DataCleaningError(
                        f"Invalid JSON at line {line_number}: {exc.msg}"
                    ) from exc
                record, actions = _validate_and_clean_record(
                    raw_record, line_number=line_number
                )
                if record["id"] in seen_ids:
                    raise DataCleaningError(
                        f"Duplicate source id at line {line_number}: {record['id']}"
                    )
                seen_ids.add(record["id"])
                entries.append((line_number, record))
                if actions:
                    records_with_changes += 1
                for action, count in actions.items():
                    action_totals[action] += count
                    action_records[action] += 1
                if (
                    progress_callback is not None
                    and progress_interval > 0
                    and line_number % progress_interval == 0
                ):
                    progress_callback(line_number)
    except UnicodeDecodeError as exc:
        raise DataCleaningError("Input JSONL is not valid UTF-8") from exc

    if expected_count is not None and len(entries) != expected_count:
        raise DataCleaningError(
            f"Record count mismatch: expected {expected_count}, got {len(entries)}"
        )

    pre_dedup_records = [record for _, record in entries]
    exact_groups_before, _ = _count_duplicate_text_groups(pre_dedup_records)
    identity_groups: defaultdict[
        tuple[str, str, str], list[tuple[int, dict[str, Any]]]
    ] = defaultdict(list)
    for entry in entries:
        identity = _decision_identity(entry[1])
        if identity is not None:
            identity_groups[identity].append(entry)

    canonical_line_numbers: set[int] = {line_number for line_number, _ in entries}
    duplicate_audit: list[dict[str, Any]] = []
    duplicate_group_count = 0
    for identity, group in identity_groups.items():
        if len(group) == 1:
            continue
        duplicate_group_count += 1
        canonical_line, canonical_record = min(
            group,
            key=lambda entry: (
                -len(entry[1]["karar_metni"]),
                0 if entry[1].get("karar_tarihi") else 1,
                entry[0],
            ),
        )
        for line_number, record in group:
            if line_number == canonical_line:
                continue
            canonical_line_numbers.remove(line_number)
            duplicate_audit.append(
                {
                    "id": record["id"],
                    "duplicate_of_id": canonical_record["id"],
                    "reason": "ayni_daire_esas_karar",
                    "daire": identity[0],
                    "esas_no": identity[1],
                    "karar_no": identity[2],
                    "dropped_text_length": len(record["karar_metni"]),
                    "kept_text_length": len(canonical_record["karar_metni"]),
                }
            )

    selected = [
        record for line_number, record in entries if line_number in canonical_line_numbers
    ]
    text_hash_counts: Counter[str] = Counter(
        hashlib.sha256(record["karar_metni"].encode("utf-8")).hexdigest()
        for record in selected
    )
    exact_groups_after = sum(1 for count in text_hash_counts.values() if count > 1)
    repeated_text_records = sum(
        count for count in text_hash_counts.values() if count > 1
    )

    warning_counts: Counter[str] = Counter()
    quality_warning_records = 0
    for record in selected:
        text_hash = hashlib.sha256(record["karar_metni"].encode("utf-8")).hexdigest()
        warnings: list[str] = []
        for field_name in ("esas_no", "karar_no", "karar_tarihi"):
            if record.get(field_name) is None:
                warnings.append(f"eksik_{field_name}")
        if record["metin_2000_karakter_sinirinda"]:
            warnings.append("kaynak_metin_2000_karakter_sinirinda")
        repeated_count = text_hash_counts[text_hash]
        if repeated_count > 1:
            warnings.append("ayni_metin_farkli_kararlarda")
        warning_counts.update(warnings)
        if warnings:
            quality_warning_records += 1
        record["karar_metni_sha256"] = text_hash
        record["karar_metni_karakter_sayisi"] = len(record["karar_metni"])
        record["ayni_metin_kayit_sayisi"] = repeated_count
        record["veri_kalite_uyarilari"] = warnings
        record["veri_kalite_durumu"] = "uyarili" if warnings else "gecerli"
        record["temizleme_surum"] = CLEANING_VERSION

    for path in (output_path, duplicates_path, stats_path):
        path.parent.mkdir(parents=True, exist_ok=True)
    output_temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    duplicates_temporary = duplicates_path.with_suffix(duplicates_path.suffix + ".tmp")
    stats_temporary = stats_path.with_suffix(stats_path.suffix + ".tmp")
    output_digest = hashlib.sha256()
    try:
        with output_temporary.open("w", encoding="utf-8", newline="\n") as stream:
            for record in selected:
                encoded = (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")
                stream.write(encoded.decode("utf-8"))
                output_digest.update(encoded)
        with duplicates_temporary.open(
            "w", encoding="utf-8", newline="\n"
        ) as stream:
            for record in duplicate_audit:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")

        stats = CleaningStats(
            cleaning_version=CLEANING_VERSION,
            input_records=len(entries),
            output_records=len(selected),
            unique_output_ids=len({record["id"] for record in selected}),
            identity_duplicate_groups=duplicate_group_count,
            identity_duplicates_removed=len(duplicate_audit),
            exact_text_duplicate_groups_before=exact_groups_before,
            exact_text_duplicate_groups_after=exact_groups_after,
            output_records_in_repeated_text_groups=repeated_text_records,
            records_with_cleaning_changes=records_with_changes,
            line_ending_records_normalized=action_records[
                "line_endings_normalized"
            ],
            html_markup_records_cleaned=action_records["html_markup_removed"],
            html_entity_records_decoded=action_records["html_entities_decoded"],
            unicode_space_records_cleaned=action_records[
                "unicode_spaces_replaced"
            ],
            unicode_space_characters_replaced=action_totals[
                "unicode_spaces_replaced"
            ],
            zero_width_records_cleaned=action_records[
                "zero_width_characters_removed"
            ],
            unicode_nfc_records_normalized=action_records[
                "unicode_nfc_normalized"
            ],
            whitespace_records_normalized=action_records[
                "whitespace_normalized"
            ],
            source_label_quote_records_cleaned=action_records[
                "source_label_quote_removed"
            ],
            missing_esas_no=sum(
                record.get("esas_no") is None for record in selected
            ),
            missing_karar_no=sum(
                record.get("karar_no") is None for record in selected
            ),
            missing_karar_tarihi=sum(
                record.get("karar_tarihi") is None for record in selected
            ),
            source_texts_at_2000_character_limit=sum(
                record["metin_2000_karakter_sinirinda"] for record in selected
            ),
            quality_warning_records=quality_warning_records,
            warning_counts=dict(sorted(warning_counts.items())),
            output_sha256=output_digest.hexdigest(),
        )
        stats_temporary.write_text(
            json.dumps(stats, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        output_temporary.replace(output_path)
        duplicates_temporary.replace(duplicates_path)
        stats_temporary.replace(stats_path)
    except Exception:
        output_temporary.unlink(missing_ok=True)
        duplicates_temporary.unlink(missing_ok=True)
        stats_temporary.unlink(missing_ok=True)
        raise
    return stats


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Clean and quality-label the 15k Yargitay raw corpus."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("data/raw/yargitay_turklegalbench_15000.jsonl"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/processed/yargitay_clean_14870.jsonl"),
    )
    parser.add_argument(
        "--duplicates",
        type=Path,
        default=Path("data/processed/yargitay_clean_duplicates.jsonl"),
    )
    parser.add_argument(
        "--stats",
        type=Path,
        default=Path("data/processed/yargitay_clean_stats.json"),
    )
    parser.add_argument("--expected-count", type=int, default=15000)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    stats = clean_corpus(
        args.input,
        args.output,
        args.duplicates,
        args.stats,
        expected_count=args.expected_count,
        progress_callback=lambda count: print(f"Validated and cleaned: {count}"),
    )
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
