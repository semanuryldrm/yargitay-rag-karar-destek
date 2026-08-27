"""Fetch a tiny JSONL sample for Day 5 validation; not a bulk scraper."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from yargitay_client import YargitayClient


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=3, choices=range(1, 11))
    parser.add_argument(
        "--output", type=Path, default=Path("data/raw/sample_decisions.jsonl")
    )
    args = parser.parse_args()

    client = YargitayClient()
    response = client.list_decisions(
        start_date="01.01.2025",
        end_date="01.12.2025",
        page_number=1,
        page_size=args.count,
    )
    container = response.get("data")
    if not isinstance(container, dict):
        raise RuntimeError(f"List endpoint error: {response.get('metadata')}")
    decisions = container.get("data") or []
    if len(decisions) != args.count:
        raise RuntimeError(f"Expected {args.count} decisions, received {len(decisions)}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as stream:
        for decision in decisions:
            detail = client.get_decision(str(decision["id"]))
            html = detail.get("data")
            if not isinstance(html, str) or not html.strip():
                raise RuntimeError(f"No detail HTML for decision {decision['id']}")
            record = {
                "id": str(decision["id"]),
                "daire": decision.get("daire"),
                "esas_no": decision.get("esasNo"),
                "karar_no": decision.get("kararNo"),
                "karar_tarihi": decision.get("kararTarihi"),
                "karar_html": html,
            }
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"Saved {len(decisions)} decisions to {args.output}")


if __name__ == "__main__":
    main()
