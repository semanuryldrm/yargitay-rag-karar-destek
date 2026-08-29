import json
import logging
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from scrape_yargitay import DecisionDataError, load_state, retry_call, run_scraper
from yargitay_client import YargitayAccessBlockedError, YargitayClientError


def summary(decision_id):
    return {
        "id": str(decision_id),
        "daire": "1. Hukuk Dairesi",
        "esasNo": f"2025/{decision_id}",
        "kararNo": f"2025/{decision_id}",
        "kararTarihi": "01.01.2025",
    }


class BulkFakeClient:
    def __init__(self, pages, failing_ids=None):
        self.pages = pages
        self.failing_ids = set(failing_ids or [])
        self.list_pages = []
        self.detail_ids = []
        self.reset_count = 0

    def list_decisions(self, **kwargs):
        page_number = kwargs["page_number"]
        self.list_pages.append(page_number)
        items = self.pages[page_number]
        return {"data": {"data": items, "recordsFiltered": len(items)}}

    def get_decision(self, decision_id):
        self.detail_ids.append(decision_id)
        if decision_id in self.failing_ids:
            raise YargitayClientError("permanent detail error")
        return {"data": f"<p>Karar {decision_id}</p>"}

    def reset_session(self):
        self.reset_count += 1


class BulkScrapeTests(unittest.TestCase):
    def setUp(self):
        self.logger = logging.getLogger(f"test-{self.id()}")
        self.logger.addHandler(logging.NullHandler())

    def run_bulk(self, client, root, **overrides):
        options = {
            "start_date": "01.01.2025",
            "end_date": "01.12.2025",
            "page_size": 3,
            "max_pages": 1,
            "output_path": root / "decisions.jsonl",
            "state_path": root / "state.json",
            "failure_path": root / "failures.jsonl",
            "logger": self.logger,
            "attempts": 2,
            "request_delay": 0,
            "retry_delay": 0,
            "sleep_fn": lambda _seconds: None,
        }
        options.update(overrides)
        return run_scraper(client, **options)

    def test_query_configuration_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.joinpath("state.json").write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "start_date": "01.01.2025",
                        "end_date": "01.12.2025",
                        "page_size": 100,
                        "last_completed_page": 1,
                        "total_saved": 0,
                        "total_failed": 0,
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(DecisionDataError, "configuration does not match"):
                load_state(
                    root / "state.json",
                    start_date="01.01.2025",
                    end_date="01.12.2025",
                    page_size=50,
                )

    def test_rate_limit_uses_longer_adaptive_backoff(self):
        calls = []
        sleeps = []

        def rate_limited_operation():
            calls.append(1)
            if len(calls) < 3:
                raise YargitayClientError("HTTP Error 429: Too Many Requests")
            return "ok"

        result = retry_call(
            rate_limited_operation,
            description="rate-limited operation",
            attempts=3,
            retry_delay=2,
            logger=self.logger,
            sleep_fn=sleeps.append,
        )
        self.assertEqual(result, "ok")
        self.assertEqual(sleeps, [30.0, 60.0])

    def test_captcha_block_is_not_retried(self):
        calls = []
        sleeps = []

        def blocked_operation():
            calls.append(1)
            raise YargitayAccessBlockedError("interactive CAPTCHA")

        with self.assertRaises(YargitayAccessBlockedError):
            retry_call(
                blocked_operation,
                description="blocked operation",
                attempts=3,
                retry_delay=2,
                logger=self.logger,
                sleep_fn=sleeps.append,
            )
        self.assertEqual(len(calls), 1)
        self.assertEqual(sleeps, [])

    def test_continues_after_final_failure_and_records_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client = BulkFakeClient({1: [summary(1), summary(2)]}, failing_ids={"1"})
            state = self.run_bulk(
                client,
                root,
                page_size=2,
                continue_on_error=True,
            )
            saved = [
                json.loads(line)
                for line in root.joinpath("decisions.jsonl").read_text().splitlines()
            ]
            failures = [
                json.loads(line)
                for line in root.joinpath("failures.jsonl").read_text().splitlines()
            ]
        self.assertEqual([record["id"] for record in saved], ["2"])
        self.assertEqual([record["id"] for record in failures], ["1"])
        self.assertEqual(failures[0]["page_number"], 1)
        self.assertEqual(state["last_completed_page"], 1)
        self.assertEqual(state["total_saved"], 1)
        self.assertEqual(state["total_failed"], 1)
        self.assertEqual(client.detail_ids, ["1", "1", "2"])

    def test_failure_file_count_must_match_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.joinpath("state.json").write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "start_date": "01.01.2025",
                        "end_date": "01.12.2025",
                        "page_size": 1,
                        "last_completed_page": 0,
                        "total_saved": 0,
                        "total_failed": 1,
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(DecisionDataError, "total_failed does not match"):
                self.run_bulk(BulkFakeClient({1: [summary(1)]}), root, page_size=1)

    def test_target_mid_page_can_resume_without_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pages = {1: [summary(1), summary(2), summary(3)]}
            first_client = BulkFakeClient(pages)
            first_state = self.run_bulk(
                first_client,
                root,
                target_count=2,
            )
            second_client = BulkFakeClient(pages)
            second_state = self.run_bulk(
                second_client,
                root,
                target_count=3,
            )
            ids = [
                json.loads(line)["id"]
                for line in root.joinpath("decisions.jsonl").read_text().splitlines()
            ]
        self.assertEqual(first_state["last_completed_page"], 0)
        self.assertEqual(first_state["total_saved"], 2)
        self.assertEqual(second_client.detail_ids, ["3"])
        self.assertEqual(second_state["last_completed_page"], 1)
        self.assertEqual(second_state["total_saved"], 3)
        self.assertEqual(ids, ["1", "2", "3"])

    def test_reached_target_avoids_network_requests(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.joinpath("decisions.jsonl").write_text(
                json.dumps({"id": "1"}) + "\n", encoding="utf-8"
            )
            root.joinpath("state.json").write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "start_date": "01.01.2025",
                        "end_date": "01.12.2025",
                        "page_size": 1,
                        "last_completed_page": 1,
                        "total_saved": 1,
                        "total_failed": 0,
                    }
                ),
                encoding="utf-8",
            )
            client = BulkFakeClient({})
            state = self.run_bulk(
                client,
                root,
                page_size=1,
                target_count=1,
            )
        self.assertEqual(state["total_saved"], 1)
        self.assertEqual(client.list_pages, [])


if __name__ == "__main__":
    unittest.main()
