import json
import logging
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from scrape_yargitay import (
    DecisionDataError,
    load_existing_ids,
    load_state,
    retry_call,
    run_scraper,
)
from yargitay_client import YargitayClientError


def summary(decision_id):
    return {
        "id": str(decision_id),
        "daire": "1. Hukuk Dairesi",
        "esasNo": f"2025/{decision_id}",
        "kararNo": f"2025/{decision_id}",
        "kararTarihi": "01.01.2025",
    }


class ResilientFakeClient:
    def __init__(self, pages, list_failures=0, detail_failures=None):
        self.pages = pages
        self.list_failures = list_failures
        self.detail_failures = dict(detail_failures or {})
        self.list_pages = []
        self.detail_ids = []
        self.reset_count = 0

    def list_decisions(self, **kwargs):
        self.list_pages.append(kwargs["page_number"])
        if self.list_failures:
            self.list_failures -= 1
            raise YargitayClientError("temporary list error")
        return {"data": {"data": self.pages[kwargs["page_number"]]}}

    def get_decision(self, decision_id):
        self.detail_ids.append(decision_id)
        if self.detail_failures.get(decision_id, 0):
            self.detail_failures[decision_id] -= 1
            raise YargitayClientError("temporary detail error")
        return {"data": f"<html>Karar {decision_id}</html>"}

    def reset_session(self):
        self.reset_count += 1


class ScraperResilienceTests(unittest.TestCase):
    def setUp(self):
        self.logger = logging.getLogger(f"test-{self.id()}")
        self.logger.addHandler(logging.NullHandler())

    def test_retry_succeeds_and_uses_linear_backoff(self):
        calls = []
        sleeps = []

        def operation():
            calls.append(1)
            if len(calls) < 3:
                raise YargitayClientError("temporary")
            return "ok"

        result = retry_call(
            operation,
            description="test operation",
            attempts=3,
            retry_delay=0.5,
            logger=self.logger,
            sleep_fn=sleeps.append,
        )
        self.assertEqual(result, "ok")
        self.assertEqual(sleeps, [0.5, 1.0])

    def test_retry_raises_after_last_attempt(self):
        with self.assertRaises(YargitayClientError):
            retry_call(
                lambda: (_ for _ in ()).throw(YargitayClientError("always")),
                description="failing operation",
                attempts=2,
                retry_delay=0,
                logger=self.logger,
                sleep_fn=lambda _seconds: None,
            )

    def test_load_existing_ids_rejects_invalid_jsonl(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "decisions.jsonl"
            output.write_text("not-json\n", encoding="utf-8")
            with self.assertRaises(DecisionDataError):
                load_existing_ids(output)

    def test_run_resumes_from_next_page_and_skips_duplicate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "decisions.jsonl"
            output.write_text(
                json.dumps({"id": "20", "karar_html": "<html>old</html>"}) + "\n",
                encoding="utf-8",
            )
            state_path = root / "state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "start_date": "01.01.2025",
                        "end_date": "01.12.2025",
                        "page_size": 2,
                        "last_completed_page": 1,
                        "total_saved": 1,
                        "total_failed": 0,
                    }
                ),
                encoding="utf-8",
            )
            client = ResilientFakeClient({2: [summary(20), summary(21)]})
            state = run_scraper(
                client,
                start_date="01.01.2025",
                end_date="01.12.2025",
                page_size=2,
                max_pages=1,
                output_path=output,
                state_path=state_path,
                logger=self.logger,
                request_delay=0,
                retry_delay=0,
                sleep_fn=lambda _seconds: None,
            )
            ids = [json.loads(line)["id"] for line in output.read_text().splitlines()]
        self.assertEqual(client.list_pages, [2])
        self.assertEqual(client.detail_ids, ["21"])
        self.assertEqual(ids, ["20", "21"])
        self.assertEqual(state["last_completed_page"], 2)
        self.assertEqual(state["total_saved"], 2)
        self.assertEqual(state["total_failed"], 0)

    def test_run_retries_list_and_detail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client = ResilientFakeClient(
                {1: [summary(1)]}, list_failures=1, detail_failures={"1": 1}
            )
            state = run_scraper(
                client,
                start_date="01.01.2025",
                end_date="01.12.2025",
                page_size=1,
                max_pages=1,
                output_path=root / "decisions.jsonl",
                state_path=root / "state.json",
                logger=self.logger,
                attempts=2,
                request_delay=0,
                retry_delay=0,
                sleep_fn=lambda _seconds: None,
            )
        self.assertEqual(client.list_pages, [1, 1])
        self.assertEqual(client.detail_ids, ["1", "1"])
        self.assertEqual(client.reset_count, 2)
        self.assertEqual(state["last_completed_page"], 1)

    def test_failed_page_does_not_advance_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_path = root / "state.json"
            client = ResilientFakeClient(
                {1: [summary(1)]}, detail_failures={"1": 2}
            )
            with self.assertRaises(YargitayClientError):
                run_scraper(
                    client,
                    start_date="01.01.2025",
                    end_date="01.12.2025",
                    page_size=1,
                    max_pages=1,
                    output_path=root / "decisions.jsonl",
                    state_path=state_path,
                    logger=self.logger,
                    attempts=2,
                    request_delay=0,
                    retry_delay=0,
                    sleep_fn=lambda _seconds: None,
                )
            self.assertFalse(state_path.exists())
            self.assertEqual(load_state(state_path)["last_completed_page"], 0)

    def test_rejects_state_and_output_count_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "decisions.jsonl"
            output.write_text(
                json.dumps({"id": "1", "karar_html": "<html>old</html>"}) + "\n",
                encoding="utf-8",
            )
            state_path = root / "state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "start_date": "01.01.2025",
                        "end_date": "01.12.2025",
                        "page_size": 1,
                        "last_completed_page": 1,
                        "total_saved": 2,
                        "total_failed": 0,
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(DecisionDataError, "does not match"):
                run_scraper(
                    ResilientFakeClient({2: [summary(2)]}),
                    start_date="01.01.2025",
                    end_date="01.12.2025",
                    page_size=1,
                    max_pages=1,
                    output_path=output,
                    state_path=state_path,
                    logger=self.logger,
                    request_delay=0,
                    retry_delay=0,
                    sleep_fn=lambda _seconds: None,
                )


if __name__ == "__main__":
    unittest.main()
