import json
import sys
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from yargitay_client import (
    YargitayAccessBlockedError,
    YargitayClient,
    YargitayClientError,
)


class FakeResponse:
    status = 200

    def __init__(self, payload):
        self._stream = BytesIO(json.dumps(payload).encode("utf-8"))

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self._stream.read()


class YargitayClientTests(unittest.TestCase):
    def test_list_request_and_utf8_response(self):
        client = YargitayClient()
        client._session_ready = True
        with patch.object(client._opener, "open") as mocked_open:
            mocked_open.side_effect = [
                FakeResponse({"prepared": True}),
                FakeResponse({"data": {"data": [{"daire": "1. Hukuk Dairesi"}]}}),
            ]
            result = client.list_decisions(
                start_date="01.01.2025", end_date="01.12.2025", page_size=1
            )
        self.assertEqual(result["data"]["data"][0]["daire"], "1. Hukuk Dairesi")
        request = mocked_open.call_args.args[0]
        sent = json.loads(request.data.decode("utf-8"))["data"]
        self.assertEqual(sent["pageNumber"], 1)
        self.assertEqual(sent["pageSize"], 1)
        self.assertTrue(
            mocked_open.call_args_list[0].args[0].full_url.endswith("/detayliArama")
        )
        self.assertTrue(
            mocked_open.call_args_list[1].args[0].full_url.endswith("/aramadetaylist")
        )

    def test_rejects_invalid_paging(self):
        with self.assertRaises(ValueError):
            YargitayClient().list_decisions(
                start_date="01.01.2025", end_date="01.12.2025", page_number=0
            )

    def test_rejects_non_json_response(self):
        response = FakeResponse({})
        response._stream = BytesIO(b"not-json")
        client = YargitayClient()
        client._session_ready = True
        with patch.object(client._opener, "open", return_value=response):
            with self.assertRaises(YargitayClientError):
                client.get_decision("123")

    def test_surfaces_application_level_error(self):
        client = YargitayClient()
        client._session_ready = True
        response = FakeResponse(
            {"data": None, "metadata": {"FMC": "ADALET_RUNTIME_EXCEPTION", "FMTE": "Hata"}}
        )
        with patch.object(client._opener, "open", return_value=response):
            with self.assertRaisesRegex(YargitayClientError, "ADALET_RUNTIME_EXCEPTION"):
                client.get_decision("123")

    def test_surfaces_captcha_as_access_block(self):
        client = YargitayClient()
        client._session_ready = True
        response = FakeResponse(
            {
                "data": None,
                "metadata": {
                    "FMC": "ADALET_RUNTIME_EXCEPTION",
                    "FMTE": "Runtime exception:{0}:DisplayCaptcha",
                },
            }
        )
        with patch.object(client._opener, "open", return_value=response):
            with self.assertRaisesRegex(YargitayAccessBlockedError, "CAPTCHA"):
                client.get_decision("123")


if __name__ == "__main__":
    unittest.main()
