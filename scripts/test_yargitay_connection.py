"""Day 5 smoke test: fetch one result page and one decision detail."""

from __future__ import annotations

from yargitay_client import YargitayClient


def main() -> None:
    client = YargitayClient()
    response = client.list_decisions(
        start_date="01.01.2025",
        end_date="01.12.2025",
        page_number=1,
        page_size=3,
    )
    container = response.get("data", response)
    decisions = container.get("data", [])
    if not decisions:
        raise RuntimeError("List endpoint returned no decisions")

    print(f"List records: {len(decisions)}")
    print(f"Filtered total: {container.get('recordsFiltered')}")
    for decision in decisions:
        print(
            decision.get("id"),
            decision.get("daire"),
            decision.get("esasNo"),
            decision.get("kararNo"),
            decision.get("kararTarihi"),
        )

    first = decisions[0]
    second_page = client.list_decisions(
        start_date="01.01.2025",
        end_date="01.12.2025",
        page_number=2,
        page_size=3,
    )["data"]["data"]
    if not second_page or second_page[0]["id"] == first["id"]:
        raise RuntimeError("Pagination did not produce a different first decision")
    print(f"Page 2 first id: {second_page[0]['id']}")

    detail = client.get_decision(str(first["id"]))
    html = detail.get("data")
    if not isinstance(html, str) or not html.strip():
        raise RuntimeError("Detail endpoint returned no HTML in the data field")
    print(f"Detail id: {first['id']}")
    print(f"Detail HTML characters: {len(html)}")
    print(f"Turkish character present: {any(c in html for c in 'çğıöşüÇĞİÖŞÜ')}")


if __name__ == "__main__":
    main()
