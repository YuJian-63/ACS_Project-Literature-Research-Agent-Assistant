import copy
import math
import unittest
from types import SimpleNamespace

from app.agent_bridge.model_telemetry import extract_server_metrics
from app.task_metrics.service import agent_metrics, evaluation_metrics, model_server_metrics


def server_response():
    return {"metrics": {"time_to_first_token_ms": 24, "time_per_output_token_ms": 5,
        "mean_itl_ms": 6, "tokens_per_second": 125,
        "telemetry": {"schema": "qwen-agent-telemetry-v1", "request_id": "req-1",
            "request": {"server_output_tokens_per_second": 80,
                "cache_hit_tokens": 40, "cache_query_tokens": 100, "prefix_cache_hit_ratio": 0.4},
            "gpu_snapshot": {"sampled_at_utc": "2026-11-22T12:00:00Z",
                "gpus": [{"uuid": "GPU-one", "gpu_utilization_percent": 70},
                    {"uuid": "GPU-two", "gpu_utilization_percent": 0}]}}}}


def model_entry(capture=None):
    return {"kind": "model", "purpose": "agent", "response": {
        "response_metadata": {"server_metrics": capture or extract_server_metrics(server_response())}}}


class TelemetryTests(unittest.TestCase):
    def test_native_units_gpu_snapshot_and_whitelist(self):
        payload = server_response()
        payload["metrics"]["secret"] = "private"
        payload["metrics"]["telemetry"]["service_window"] = {"all_users": 999}
        capture = extract_server_metrics(payload)
        self.assertEqual(capture["ttft_ms"], 24)
        self.assertEqual(capture["tpot_ms"], 5)
        self.assertEqual(capture["mean_itl_ms"], 6)
        self.assertEqual(capture["tokens_per_second"], 125)
        self.assertEqual(capture["gpus"][1]["utilization_percent"], 0)
        self.assertEqual(capture["gpu_sampled_at"], "2026-11-22T12:00:00Z")
        self.assertNotIn("secret", str(capture))
        self.assertNotIn("all_users", str(capture))

    def test_missing_metrics_and_explicit_server_throughput_fallback(self):
        self.assertIsNone(extract_server_metrics({"usage": {"completion_tokens": 20}}))
        payload = server_response()
        payload["metrics"] = {"telemetry": payload["metrics"]["telemetry"]}
        payload["metrics"]["telemetry"]["request"]["prefill_time_ms"] = 123
        capture = extract_server_metrics(payload)
        self.assertIsNone(capture["ttft_ms"])
        self.assertIsNone(capture["tpot_ms"])
        self.assertIsNone(capture["mean_itl_ms"])
        self.assertEqual(capture["tokens_per_second"], 80)
        self.assertIn("server_output_tokens_per_second", capture["sources"]["tokens_per_second"])

    def test_native_mean_itl_supplies_missing_tpot_before_streaming_fallback(self):
        for source, value in (("mean_itl_ms", 6), ("mean_inter_token_latency_ms", 6), ("mean_itl_ms", 0)):
            with self.subTest(source=source, value=value):
                payload = server_response()
                payload["metrics"].pop("time_per_output_token_ms")
                payload["metrics"].pop("mean_itl_ms")
                payload["metrics"][source] = value
                payload["metrics"]["telemetry"]["request"]["server_mean_time_per_output_token_ms"] = 12
                capture = extract_server_metrics(payload)
                self.assertEqual(capture["tpot_ms"], value)
                self.assertEqual(capture["mean_itl_ms"], value)
                self.assertEqual(capture["sources"]["tpot_ms"], "metrics." + source)

    def test_invalid_numbers_and_gpu_readings_are_missing(self):
        payload = server_response()
        payload["metrics"].update(time_to_first_token_ms=math.nan,
            time_per_output_token_ms=-1, mean_itl_ms=True, tokens_per_second=math.inf)
        payload["metrics"]["telemetry"]["request"]["server_output_tokens_per_second"] = math.inf
        payload["metrics"]["telemetry"]["gpu_snapshot"]["gpus"][0]["gpu_utilization_percent"] = 101
        capture = extract_server_metrics(payload)
        for key in ("ttft_ms", "tpot_ms", "mean_itl_ms", "tokens_per_second"):
            self.assertIsNone(capture[key])
        self.assertIsNone(capture["gpus"][0]["utilization_percent"])

    def test_bad_optional_telemetry_does_not_hide_native_metrics(self):
        for value in (None, [], "bad", {"gpu_snapshot": {"gpus": [None, "bad"]}}):
            payload = server_response()
            payload["metrics"]["telemetry"] = value
            self.assertEqual(extract_server_metrics(payload)["ttft_ms"], 24)


class TaskMetricsTests(unittest.TestCase):
    def test_agent_usage_preserves_unknown_tokens(self):
        view = agent_metrics({"usage": {"agent_steps": 4, "model_calls": 6, "tool_calls": 3,
            "input_tokens": None, "output_tokens": 30, "total_tokens": None,
            "token_usage_complete": False}})
        self.assertEqual(view["agent_steps"], 4)
        self.assertIsNone(view["total_tokens"])
        self.assertFalse(view["token_usage_complete"])
        self.assertIsNone(agent_metrics(None)["agent_steps"])

    def test_request_means_counts_and_latest_gpu_snapshot(self):
        first = extract_server_metrics(server_response())
        second = copy.deepcopy(first)
        second.update(ttft_ms=36, gpu_sampled_at="2026-11-22T12:00:01Z")
        second["gpus"][0]["utilization_percent"] = 90
        result = {"usage": {"model_calls": 3}, "trace": [model_entry(first),
            {"kind": "tool"}, model_entry(second), {"kind": "model", "error": "timeout"}]}
        view = model_server_metrics(result)
        self.assertEqual(view["status"], "partial")
        self.assertEqual(view["model_calls_total"], 3)
        self.assertEqual(view["observed_model_calls"], 3)
        self.assertEqual(view["measured_model_calls"], 2)
        self.assertEqual(view["ttft_ms"], {"mean": 30, "samples": 2,
            "source": "metrics.time_to_first_token_ms", "unavailable_reason": None})
        self.assertEqual(view["gpus"][0]["utilization_percent"], 90)
        self.assertEqual(view["gpus"][0]["call_index"], 2)
        self.assertIsNone(view["requests"][2]["ttft_ms"])

    def test_historical_and_queued_tasks_do_not_fabricate_metrics(self):
        for result in (None, {}, {"usage": {"model_calls": 4}, "trace": [{"kind": "model"}]}):
            view = model_server_metrics(result)
            self.assertEqual(view["status"], "unavailable")
            self.assertIsNone(view["ttft_ms"]["mean"])
            self.assertEqual(view["ttft_ms"]["samples"], 0)
            self.assertEqual(view["gpus"], [])

    def test_historical_mean_itl_supplies_tpot_in_task_details(self):
        capture = extract_server_metrics(server_response())
        capture["tpot_ms"] = None
        capture["sources"].pop("tpot_ms")
        view = model_server_metrics({"usage": {"model_calls": 1}, "trace": [model_entry(capture)]})
        self.assertEqual(view["tpot_ms"], {"mean": 6, "samples": 1,
            "source": "metrics.mean_itl_ms", "unavailable_reason": None})
        self.assertEqual(view["requests"][0]["tpot_ms"], 6)
        self.assertEqual(view["requests"][0]["mean_itl_ms"], 6)

    def test_untrusted_mean_itl_cannot_supply_historical_tpot(self):
        capture = extract_server_metrics(server_response())
        capture["tpot_ms"] = None
        capture["sources"].pop("tpot_ms")
        capture["sources"]["mean_itl_ms"] = "metrics.untrusted"
        view = model_server_metrics({"usage": {"model_calls": 1}, "trace": [model_entry(capture)]})
        self.assertIsNone(view["requests"][0]["tpot_ms"])
        self.assertIsNone(view["requests"][0]["mean_itl_ms"])

    def test_historical_native_mean_itl_precedes_streaming_tpot(self):
        capture = extract_server_metrics(server_response())
        capture["tpot_ms"] = 12
        capture["sources"]["tpot_ms"] = "metrics.telemetry.request.server_mean_time_per_output_token_ms"
        view = model_server_metrics({"usage": {"model_calls": 1}, "trace": [model_entry(capture)]})
        self.assertEqual(view["tpot_ms"]["mean"], 6)
        self.assertEqual(view["tpot_ms"]["source"], "metrics.mean_itl_ms")

    def test_different_tpot_sources_remain_separate_when_aggregating(self):
        first = extract_server_metrics(server_response())
        second = copy.deepcopy(first)
        second["tpot_ms"] = None
        second["sources"].pop("tpot_ms")
        view = model_server_metrics({"usage": {"model_calls": 2},
            "trace": [model_entry(first), model_entry(second)]})
        self.assertEqual(view["tpot_ms"]["samples"], 2)
        self.assertIsNone(view["tpot_ms"]["mean"])
        self.assertEqual(view["tpot_ms"]["unavailable_reason"], "MIXED_SOURCES")
        self.assertEqual([request["tpot_ms"] for request in view["requests"]], [5, 6])

    def test_mixed_timing_scopes_do_not_get_one_misleading_average(self):
        first = extract_server_metrics(server_response())
        second = copy.deepcopy(first)
        second["sources"]["ttft_ms"] = "metrics.telemetry.request.server_time_to_first_output_event_ms"
        view = model_server_metrics({"usage": {"model_calls": 2}, "trace": [model_entry(first), model_entry(second)]})
        self.assertEqual(view["ttft_ms"]["samples"], 2)
        self.assertIsNone(view["ttft_ms"]["mean"])
        self.assertEqual(view["ttft_ms"]["unavailable_reason"], "MIXED_SOURCES")

    def test_free_form_trace_cannot_crash_or_leak_into_metrics(self):
        capture = extract_server_metrics(server_response())
        capture["sources"]["ttft_ms"] = ["invalid-source"]
        entry = model_entry(capture)
        entry["messages"] = [{"content": "private-input"}]
        view = model_server_metrics({"usage": {"model_calls": 1}, "trace": [entry]})
        self.assertIsNone(view["requests"][0]["ttft_ms"])
        self.assertNotIn("private-input", str(view))

    def test_complete_capture_is_available_and_missing_gpu_is_partial(self):
        result = {"usage": {"model_calls": 1}, "trace": [model_entry()]}
        self.assertEqual(model_server_metrics(result)["status"], "available")
        result["trace"][0]["response"]["response_metadata"]["server_metrics"]["gpus"] = []
        self.assertEqual(model_server_metrics(result)["status"], "partial")

    def test_evaluation_has_five_stable_dimensions_and_no_fake_zero(self):
        settings = SimpleNamespace(evaluation_enabled=False, evaluation_configured=False)
        empty = evaluation_metrics(None, settings)
        self.assertEqual(len(empty["dimensions"]), 5)
        self.assertIsNone(empty["overall_score"])
        self.assertTrue(all(value["score"] is None for value in empty["dimensions"].values()))
        row = SimpleNamespace(id=None, status="succeeded", error_code=None, config={"model": "deepseek-chat"},
            report={"assessment": "insufficient_evidence", "overall_score": None,
                "dimensions": {"clarity": {"score": None, "reason": "No evidence"}}})
        self.assertEqual(evaluation_metrics(row, settings)["dimensions"]["clarity"]["reason"], "No evidence")
        row.status = "failed"
        row.report = {"overall_score": 100, "dimensions": {"clarity": {"score": 5, "reason": "Old"}}}
        self.assertIsNone(evaluation_metrics(row, settings)["overall_score"])


if __name__ == "__main__":
    unittest.main()
