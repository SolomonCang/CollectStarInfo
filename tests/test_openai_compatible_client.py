from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

import requests

from src.astro_agent.clients.openai_compatible_client import OpenAICompatibleClient


class OpenAICompatibleClientTest(unittest.TestCase):
    @patch("src.astro_agent.clients.deepseek_client.requests.post")
    def test_connection_uses_minimal_chat_completions_request(self, post: Mock) -> None:
        response = Mock(ok=True)
        response.json.return_value = {
            "choices": [{"message": {"content": "OK"}}]
        }
        post.return_value = response
        client = OpenAICompatibleClient(
            api_key="secret-token",
            base_url="https://provider.example/v1",
            model="example-model",
            timeout_sec=9,
        )

        self.assertEqual(client.test_connection(), "OK")
        _, kwargs = post.call_args
        self.assertEqual(post.call_args.args[0], "https://provider.example/v1/chat/completions")
        self.assertEqual(kwargs["timeout"], 9)
        self.assertEqual(kwargs["json"]["max_tokens"], 4)
        self.assertEqual(kwargs["json"]["model"], "example-model")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer secret-token")

    @patch("src.astro_agent.clients.deepseek_client.requests.post")
    def test_provider_error_does_not_include_api_key(self, post: Mock) -> None:
        post.return_value = Mock(ok=False, status_code=401, text="invalid credentials")
        client = OpenAICompatibleClient(
            api_key="never-return-this-key",
            base_url="https://provider.example/v1",
            model="example-model",
        )

        with self.assertRaisesRegex(RuntimeError, "LLM HTTP 401") as raised:
            client.test_connection()
        self.assertNotIn("never-return-this-key", str(raised.exception))

    @patch("src.astro_agent.clients.deepseek_client.requests.post")
    def test_timeout_is_propagated_for_api_error_handling(self, post: Mock) -> None:
        post.side_effect = requests.Timeout("provider timeout")
        client = OpenAICompatibleClient(
            api_key="secret-token",
            base_url="https://provider.example/v1",
            model="example-model",
            timeout_sec=3,
        )

        with self.assertRaises(requests.Timeout):
            client.test_connection()


if __name__ == "__main__":
    unittest.main()
