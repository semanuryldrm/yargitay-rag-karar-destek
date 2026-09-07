import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.lmstudio_chat import ChatClientError, LMStudioChatClient


class FakeHTTPResponse:
    def __init__(self, payload):
        self.body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return self.body


def valid_chat_response(content="Kaynak tespiti [K1]."):
    return {
        "model_instance_id": "google/gemma-4-12b-qat",
        "output": [{"type": "message", "content": content}],
        "stats": {
            "input_tokens": 100,
            "total_output_tokens": 20,
            "reasoning_output_tokens": 0,
            "tokens_per_second": 30.5,
            "time_to_first_token_seconds": 0.2,
            "model_load_time_seconds": 0.0,
        },
        "response_id": "resp_test",
    }


class LMStudioChatClientTests(unittest.TestCase):
    def test_lists_model_and_sends_utf8_non_reasoning_chat(self):
        calls = []

        def fake_urlopen(request, timeout):
            calls.append((request, timeout))
            if request.full_url.endswith("/v1/models"):
                return FakeHTTPResponse(
                    {"data": [{"id": "google/gemma-4-12b-qat"}]}
                )
            return FakeHTTPResponse(valid_chat_response("Türkçe cevap [K1]."))

        client = LMStudioChatClient(timeout_seconds=12)
        with patch("scripts.lmstudio_chat.urlopen", side_effect=fake_urlopen):
            self.assertEqual(
                client.ensure_model_available(), ("google/gemma-4-12b-qat",)
            )
            result = client.generate(
                system_prompt="Yalnızca kaynakları kullan.",
                input_text="İş sözleşmesi feshedildi; kaynak [K1].",
                max_output_tokens=300,
            )

        self.assertEqual(result.text, "Türkçe cevap [K1].")
        self.assertEqual(result.stats["reasoning_output_tokens"], 0)
        request = calls[1][0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["reasoning"], "off")
        self.assertFalse(payload["stream"])
        self.assertEqual(payload["temperature"], 0)
        self.assertIn("İş sözleşmesi", payload["input"])
        self.assertEqual(
            request.headers["Content-type"], "application/json; charset=utf-8"
        )

    def test_rejects_wrong_model_missing_message_and_reasoning_tokens(self):
        cases = []
        wrong_model = valid_chat_response()
        wrong_model["model_instance_id"] = "another-model"
        cases.append(wrong_model)
        missing_message = valid_chat_response()
        missing_message["output"] = []
        cases.append(missing_message)
        reasoning = valid_chat_response()
        reasoning["stats"]["reasoning_output_tokens"] = 3
        cases.append(reasoning)

        for response in cases:
            with self.subTest(response=response):
                client = LMStudioChatClient()
                with patch(
                    "scripts.lmstudio_chat.urlopen",
                    return_value=FakeHTTPResponse(response),
                ):
                    with self.assertRaises(ChatClientError):
                        client.generate(
                            system_prompt="Sistem talimatı.",
                            input_text="Yeterince uzun kullanıcı girdisi.",
                        )

    def test_rejects_invalid_inputs_and_unavailable_model(self):
        with self.assertRaises(ChatClientError):
            LMStudioChatClient(timeout_seconds=0)
        client = LMStudioChatClient()
        with self.assertRaises(ChatClientError):
            client.generate(system_prompt="", input_text="Geçerli girdi")
        with patch(
            "scripts.lmstudio_chat.urlopen",
            return_value=FakeHTTPResponse({"data": [{"id": "embedding-only"}]}),
        ):
            with self.assertRaisesRegex(ChatClientError, "not available"):
                client.ensure_model_available()


if __name__ == "__main__":
    unittest.main()
