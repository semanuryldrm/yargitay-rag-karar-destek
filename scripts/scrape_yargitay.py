"""Fetch and validate one controlled page of raw Yargitay decisions.

Day 6 scope intentionally excludes retries, delays, logging, deduplication,
resume state, and bulk downloading. Those controls are added in later stages.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Protocol, TypedDict

from yargitay_client import YargitayClient


class DecisionDataError(RuntimeError):
    """Raised when Yargitay returns an incomplete or unexpected decision record."""


class DecisionRecord(TypedDict):
    id: str
    daire: str
    esas_no: str
    karar_no: str
    karar_tarihi: str
    karar_html: str


class YargitayClientProtocol(Protocol):
    def list_decisions(
        self,
        *,
        start_date: str,
        end_date: str,
        page_number: int,
        page_size: int,
    ) -> dict[str, Any]: ...

    def get_decision(self, decision_id: str) -> dict[str, Any]: ...


LIST_FIELDS = {
    "id": "id",
    "daire": "daire",
    "esasNo": "esas_no",
    "kararNo": "karar_no",
    "kararTarihi": "karar_tarihi",
}


def extract_list_items(response: dict[str, Any]) -> list[dict[str, Any]]:
    container = response.get("data")
    if not isinstance(container, dict):
        raise DecisionDataError("List response does not contain a data object")
    items = container.get("data")
    if not isinstance(items, list):
        raise DecisionDataError("List response data field is not a list")
    return items


def build_decision_record(
    summary: dict[str, Any], detail_response: dict[str, Any]
) -> DecisionRecord:
    record: dict[str, str] = {}
    for source_name, target_name in LIST_FIELDS.items():
        value = summary.get(source_name)
        if value is None or not str(value).strip():
            raise DecisionDataError(f"Decision summary is missing {source_name}")
        record[target_name] = str(value).strip()

    html = detail_response.get("data")
    if not isinstance(html, str) or not html.strip():
        raise DecisionDataError(f"Decision {record['id']} has no detail HTML")
    record["karar_html"] = html
    return DecisionRecord(**record)


def fetch_decision_page(
    client: YargitayClientProtocol,
    *,
    start_date: str,
    end_date: str,
    page_number: int,
    page_size: int,
) -> list[DecisionRecord]:
    list_response = client.list_decisions(
        start_date=start_date,
        end_date=end_date,
        page_number=page_number,
        page_size=page_size,
    )
    summaries = extract_list_items(list_response)
    if len(summaries) != page_size:
        raise DecisionDataError(
            f"Expected {page_size} list records, received {len(summaries)}"
        )

    records: list[DecisionRecord] = []
    for summary in summaries:
        decision_id = summary.get("id")
        if decision_id is None or not str(decision_id).strip():
            raise DecisionDataError("Decision summary is missing id")
        detail_response = client.get_decision(str(decision_id))
        records.append(build_decision_record(summary, detail_response))
    return records


def write_jsonl(records: list[DecisionRecord], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch one controlled page of raw Yargitay decisions"
    )
    parser.add_argument("--start-date", default="01.01.2025")
    parser.add_argument("--end-date", default="01.12.2025")
    parser.add_argument("--page-number", type=int, default=1)
    parser.add_argument("--page-size", type=int, default=5, choices=range(1, 101))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/raw/day6_sample_decisions.jsonl"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    records = fetch_decision_page(
        YargitayClient(),
        start_date=args.start_date,
        end_date=args.end_date,
        page_number=args.page_number,
        page_size=args.page_size,
    )
    write_jsonl(records, args.output)
    print(
        f"Saved {len(records)} decisions from page {args.page_number} "
        f"to {args.output}"
    )


if __name__ == "__main__":
    main()
