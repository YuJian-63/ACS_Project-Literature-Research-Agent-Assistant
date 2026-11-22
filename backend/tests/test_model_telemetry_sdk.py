import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx

from app.agent_bridge import metrics_job, model_telemetry

HAS_MODEL_SDK = importlib.util.find_spec("langchain_openai") is not None


@unittest.skipUnless(HAS_MODEL_SDK, "Run with the installed Agent Python to verify the real model SDK")
class ModelSDKTests(unittest.TestCase):
    def test_real_invoke_keeps_cache_usage_without_custom_server_metrics(self):
        from langchain_openai import ChatOpenAI

        body = {"id": "chat-cache", "object": "chat.completion", "created": 1, "model": "offline-probe",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "Answer"},
                "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 5, "total_tokens": 105,
                "prompt_tokens_details": {"cached_tokens": 40}}}
        with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body))) as client:
            model_telemetry.install()
            model = ChatOpenAI(model="offline-probe", api_key="offline-only", base_url="http://offline.invalid/v1",
                http_client=client, streaming=False, max_retries=0, use_responses_api=False)
            response = model.invoke("Offline cached request")
        capture = response.model_dump(mode="json")["response_metadata"]["server_metrics"]
        self.assertEqual(capture["cache_hit_tokens"], 40)
        self.assertEqual(capture["cache_query_tokens"], 100)
        self.assertEqual(capture["cache_hit_ratio"], 0.4)
        self.assertIsNone(capture["ttft_ms"])
        self.assertEqual(response.usage_metadata["total_tokens"], 105)
        self.assertEqual(response.usage_metadata["input_token_details"]["cache_read"], 40)

    def test_real_invoke_preserves_server_metrics_usage_and_tool_calls(self):
        from langchain_openai import ChatOpenAI

        body = {"id": "chat-test", "object": "chat.completion", "created": 1, "model": "offline-probe",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "Answer",
                "tool_calls": [{"id": "call-test", "type": "function", "function": {
                    "name": "open_paper", "arguments": json.dumps({"paper_id": "test"})}}]},
                "finish_reason": "tool_calls"}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 4, "total_tokens": 16},
            "metrics": {"time_to_first_token_ms": 12, "mean_itl_ms": 3,
                "tokens_per_second": 75, "private": "must-not-copy"}}
        with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body))) as client:
            model_telemetry.install()
            installed = ChatOpenAI._create_chat_result
            model_telemetry.install()
            self.assertIs(ChatOpenAI._create_chat_result, installed)
            model = ChatOpenAI(model="offline-probe", api_key="offline-only", base_url="http://offline.invalid/v1",
                http_client=client, streaming=False, max_retries=0, use_responses_api=False)
            response = model.invoke("Offline request")
            self.assertEqual(response.response_metadata["server_metrics"]["ttft_ms"], 12)
            self.assertEqual(response.response_metadata["server_metrics"]["tpot_ms"], 3)
            self.assertEqual(response.response_metadata["server_metrics"]["mean_itl_ms"], 3)
            self.assertEqual(response.response_metadata["server_metrics"]["sources"]["tpot_ms"], "metrics.mean_itl_ms")
            self.assertNotIn("private", str(response.response_metadata["server_metrics"]))
            self.assertEqual(response.usage_metadata["total_tokens"], 16)
            self.assertEqual(response.tool_calls[0]["name"], "open_paper")
            body.pop("metrics")
            response = model.invoke("Another offline request")
            self.assertNotIn("server_metrics", response.response_metadata)
            body["metrics"] = {"time_to_first_token_ms": 12}
            with patch.object(model_telemetry, "extract_server_metrics", side_effect=ValueError("broken optional data")):
                self.assertEqual(model.invoke("Still works").content, "Answer")


class LauncherTests(unittest.TestCase):
    def test_bootstrap_requires_no_sdk_and_execution_installs_capture(self):
        for research in (False, True):
            with self.subTest(research=research), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                (directory / "research_job.py").write_text(
                    "def run_research():\n    return 17\ndef main():\n    return "
                    + ("run_research()" if research else "23") + "\n", encoding="utf-8")
                install = Mock()
                with patch.object(metrics_job, "__file__", str(directory / "run_job.py")), patch.dict(
                    "sys.modules", {"model_telemetry": SimpleNamespace(install=install)}):
                    self.assertEqual(metrics_job.main(), 17 if research else 23)
                self.assertEqual(install.call_count, int(research))


if __name__ == "__main__":
    unittest.main()
