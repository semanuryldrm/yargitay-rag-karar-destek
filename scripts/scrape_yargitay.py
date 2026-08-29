"""Resumable and polite raw-decision scraper for the public Yargitay service."""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path
from typing import Any, Callable, Protocol, TypeVar, TypedDict

from yargitay_client import YargitayClient, YargitayClientError


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

    def reset_session(self) -> None: ...


class ScrapeState(TypedDict):
    last_completed_page: int
    total_saved: int


LIST_FIELDS = {
    "id": "id",
    "daire": "daire",
    "esasNo": "esas_no",
    "kararNo": "karar_no",
    "kararTarihi": "karar_tarihi",
}

T = TypeVar("T")
LOGGER_NAME = "yargitay_scraper"


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


def append_jsonl(records: list[DecisionRecord], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_existing_ids(output_path: Path) -> set[str]:
    if not output_path.exists():
        return set()
    decision_ids: set[str] = set()
    with output_path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise DecisionDataError(
                    f"Invalid JSONL at {output_path}:{line_number}"
                ) from exc
            decision_id = record.get("id") if isinstance(record, dict) else None
            if decision_id is None or not str(decision_id).strip():
                raise DecisionDataError(
                    f"Missing decision id at {output_path}:{line_number}"
                )
            decision_ids.add(str(decision_id))
    return decision_ids


def load_state(state_path: Path) -> ScrapeState:
    if not state_path.exists():
        return ScrapeState(last_completed_page=0, total_saved=0)
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DecisionDataError(f"Invalid state JSON: {state_path}") from exc
    if not isinstance(state, dict):
        raise DecisionDataError("Scrape state root must be an object")
    last_page = state.get("last_completed_page")
    total_saved = state.get("total_saved")
    if not isinstance(last_page, int) or last_page < 0:
        raise DecisionDataError("Invalid last_completed_page in scrape state")
    if not isinstance(total_saved, int) or total_saved < 0:
        raise DecisionDataError("Invalid total_saved in scrape state")
    return ScrapeState(last_completed_page=last_page, total_saved=total_saved)


def save_state(state_path: Path, state: ScrapeState) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = state_path.with_suffix(state_path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary_path.replace(state_path)


def retry_call(
    operation: Callable[[], T],
    *,
    description: str,
    attempts: int,
    retry_delay: float,
    logger: logging.Logger,
    sleep_fn: Callable[[float], None] = time.sleep,
    on_retry: Callable[[], None] | None = None,
) -> T:
    if attempts < 1:
        raise ValueError("attempts must be at least 1")
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except (YargitayClientError, DecisionDataError) as exc:
            if attempt == attempts:
                logger.error("%s failed after %s attempts: %s", description, attempts, exc)
                raise
            wait_seconds = retry_delay * attempt
            logger.warning(
                "%s failed on attempt %s/%s: %s; retrying in %.2f seconds",
                description,
                attempt,
                attempts,
                exc,
                wait_seconds,
            )
            if on_retry is not None:
                on_retry()
            sleep_fn(wait_seconds)
    raise AssertionError("retry loop ended unexpectedly")


def setup_logging(log_path: Path) -> logging.Logger:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for handler in logger.handlers:
        handler.close()
    logger.handlers.clear()
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    return logger


def run_scraper(
    client: YargitayClientProtocol,
    *,
    start_date: str,
    end_date: str,
    page_size: int,
    max_pages: int,
    output_path: Path,
    state_path: Path,
    logger: logging.Logger,
    attempts: int = 3,
    retry_delay: float = 2.0,
    request_delay: float = 1.0,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> ScrapeState:
    if max_pages < 1:
        raise ValueError("max_pages must be at least 1")
    if request_delay < 0 or retry_delay < 0:
        raise ValueError("delay values cannot be negative")

    state = load_state(state_path)
    existing_ids = load_existing_ids(output_path)
    if state["total_saved"] != len(existing_ids):
        raise DecisionDataError(
            "Scrape state total_saved does not match unique ids in output JSONL"
        )
    first_page = state["last_completed_page"] + 1
    logger.info(
        "Starting from page %s with %s existing decisions", first_page, len(existing_ids)
    )

    for page_number in range(first_page, first_page + max_pages):
        logger.info("Fetching list page %s", page_number)
        def fetch_summaries() -> list[dict[str, Any]]:
            list_response = client.list_decisions(
                start_date=start_date,
                end_date=end_date,
                page_number=page_number,
                page_size=page_size,
            )
            page_summaries = extract_list_items(list_response)
            if len(page_summaries) != page_size:
                raise DecisionDataError(
                    f"Expected {page_size} list records, received {len(page_summaries)}"
                )
            return page_summaries

        summaries = retry_call(
            fetch_summaries,
            description=f"list page {page_number}",
            attempts=attempts,
            retry_delay=retry_delay,
            logger=logger,
            sleep_fn=sleep_fn,
            on_retry=client.reset_session,
        )

        page_records: list[DecisionRecord] = []
        page_ids: set[str] = set()
        for summary in summaries:
            decision_id_value = summary.get("id")
            if decision_id_value is None or not str(decision_id_value).strip():
                raise DecisionDataError("Decision summary is missing id")
            decision_id = str(decision_id_value)
            if decision_id in existing_ids or decision_id in page_ids:
                logger.info("Skipping duplicate decision %s", decision_id)
                continue
            if request_delay:
                sleep_fn(request_delay)
            record = retry_call(
                lambda decision_id=decision_id, summary=summary: build_decision_record(
                    summary, client.get_decision(decision_id)
                ),
                description=f"decision detail {decision_id}",
                attempts=attempts,
                retry_delay=retry_delay,
                logger=logger,
                sleep_fn=sleep_fn,
                on_retry=client.reset_session,
            )
            page_records.append(record)
            page_ids.add(decision_id)

        append_jsonl(page_records, output_path)
        existing_ids.update(page_ids)
        state = ScrapeState(
            last_completed_page=page_number,
            total_saved=len(existing_ids),
        )
        save_state(state_path, state)
        logger.info(
            "Completed page %s; saved %s new decisions; total %s",
            page_number,
            len(page_records),
            state["total_saved"],
        )
    return state


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch Yargitay decisions with retry, logging, and resume state"
    )
    parser.add_argument("--start-date", default="01.01.2025")
    parser.add_argument("--end-date", default="01.12.2025")
    parser.add_argument("--page-size", type=int, default=3, choices=range(1, 101))
    parser.add_argument("--max-pages", type=int, default=1)
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--retry-delay", type=float, default=2.0)
    parser.add_argument("--request-delay", type=float, default=1.0)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/raw/decisions.jsonl"),
    )
    parser.add_argument(
        "--state", type=Path, default=Path("data/raw/scrape_state.json")
    )
    parser.add_argument("--log", type=Path, default=Path("logs/scraper.log"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logger = setup_logging(args.log)
    state = run_scraper(
        YargitayClient(),
        start_date=args.start_date,
        end_date=args.end_date,
        page_size=args.page_size,
        max_pages=args.max_pages,
        output_path=args.output,
        state_path=args.state,
        logger=logger,
        attempts=args.attempts,
        retry_delay=args.retry_delay,
        request_delay=args.request_delay,
    )
    print(
        f"Last completed page: {state['last_completed_page']}; "
        f"total saved: {state['total_saved']}"
    )


if __name__ == "__main__":
    main()
