"""Fetch a tiny JSONL sample for Day 5 validation; not a bulk scraper."""

from __future__ import annotations

import argparse
from pathlib import Path

from scrape_yargitay import fetch_decision_page, write_jsonl
from yargitay_client import YargitayClient


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=3, choices=range(1, 11))
    parser.add_argument(
        "--output", type=Path, default=Path("data/raw/sample_decisions.jsonl")
    )
    args = parser.parse_args()

    records = fetch_decision_page(
        YargitayClient(),
        start_date="01.01.2025",
        end_date="01.12.2025",
        page_number=1,
        page_size=args.count,
    )
    write_jsonl(records, args.output)
    print(f"Saved {len(records)} decisions to {args.output}")


if __name__ == "__main__":
    main()
