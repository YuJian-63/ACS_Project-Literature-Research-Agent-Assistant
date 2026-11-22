import unittest

from app.agent_bridge.model_telemetry import extract_server_metrics
from app.task_metrics.service import model_server_metrics


def cache_response(hits, queries):
    return {"usage": {"prompt_tokens": queries, "prompt_tokens_details": {"cached_tokens": hits}}}


def cache_entry(hits, queries):
    return {"kind": "model", "response": {"response_metadata": {
        "server_metrics": extract_server_metrics(cache_response(hits, queries))}}}


class CacheTelemetryTests(unittest.TestCase):
    def test_usage_only_responses_keep_cache_tokens_and_calculate_ratio(self):
        capture = extract_server_metrics(cache_response(40, 100))
        self.assertIsNotNone(capture)
        self.assertEqual(capture["cache_hit_tokens"], 40)
        self.assertEqual(capture["cache_query_tokens"], 100)
        self.assertEqual(capture["cache_hit_ratio"], 0.4)
        self.assertEqual(capture["sources"]["cache_hit_tokens"], "usage.prompt_tokens_details.cached_tokens")

    def test_request_telemetry_is_supported_without_global_cache_counters(self):
        capture = extract_server_metrics({"metrics": {"telemetry": {
            "request": {"cache_hit_tokens": 20, "cache_query_tokens": 80, "prefix_cache_hit_ratio": 0.99},
            "service_window": {"cache_hit_tokens": 99999, "cache_query_tokens": 99999},
            "service_cache_snapshot": {"prefix_cache_hits_total": 99999}}}})
        self.assertEqual(capture["cache_hit_tokens"], 20)
        self.assertEqual(capture["cache_hit_ratio"], 0.25)
        self.assertEqual(capture["sources"]["cache_query_tokens"], "metrics.telemetry.request.cache_query_tokens")
        self.assertNotIn("99999", str(capture))

    def test_raw_usage_has_priority_and_is_not_added_to_duplicate_telemetry(self):
        payload = cache_response(40, 100)
        payload["metrics"] = {"telemetry": {"request": {"cache_hit_tokens": 20, "cache_query_tokens": 80}}}
        capture = extract_server_metrics(payload)
        self.assertEqual(capture["cache_hit_tokens"], 40)
        self.assertEqual(capture["cache_hit_ratio"], 0.4)

    def test_invalid_counts_and_ratio_without_counts_are_not_measurements(self):
        cases = [(True, 10), (1, False), (-1, 10), (1.5, 10), (11, 10), (1, 10.0), (None, 10), (1, None)]
        for hits, queries in cases:
            with self.subTest(hits=hits, queries=queries):
                self.assertIsNone(extract_server_metrics(cache_response(hits, queries)))
        view = model_server_metrics({"usage": {"model_calls": 1}, "trace": [{"kind": "model", "response": {
            "response_metadata": {"token_usage": {"prompt_tokens": 100}, "server_metrics": {
                "schema": "backend-model-metrics-v1", "cache_hit_ratio": 0.8}}}}]})
        self.assertIsNone(view["cache_hit_tokens"])
        self.assertIsNone(view["cache_hit_ratio"])


class TaskCacheMetricsTests(unittest.TestCase):
    def test_task_ratio_is_token_weighted_and_duplicate_sources_are_not_counted(self):
        entry = cache_entry(20, 100)
        entry["response"]["usage_metadata"] = {"input_tokens": 100, "input_token_details": {"cache_read": 20}}
        view = model_server_metrics({"usage": {"model_calls": 2}, "trace": [entry, cache_entry(720, 900)]})
        self.assertEqual(view["cache_hit_tokens"], 740)
        self.assertEqual(view["cache_query_tokens"], 1000)
        self.assertAlmostEqual(view["cache_hit_ratio"], 0.74)
        self.assertTrue(view["cache_usage_complete"])
        self.assertEqual(view["cache_measured_model_calls"], 2)
        self.assertEqual(view["requests"][0]["cache_hit_ratio"], 0.2)

    def test_cache_only_calls_are_partial_model_server_measurements(self):
        view = model_server_metrics({"usage": {"model_calls": 1}, "trace": [cache_entry(10, 20)]})
        self.assertEqual(view["status"], "partial")
        self.assertTrue(view["requests"][0]["available"])
        self.assertEqual(view["measured_model_calls"], 1)
        self.assertIsNone(view["requests"][0]["ttft_ms"])

    def test_old_agent_sdk_usage_is_read_without_requiring_new_capture(self):
        entries = [{"kind": "model", "response": {
            "usage_metadata": {"input_tokens": 100, "input_token_details": {"cache_read": 40}}}},
            {"kind": "model", "response": {"response_metadata": {"token_usage": {
                "prompt_tokens": 200, "prompt_tokens_details": {"cached_tokens": 50}}}}}]
        view = model_server_metrics({"usage": {"model_calls": 2}, "trace": entries})
        self.assertEqual(view["cache_hit_tokens"], 90)
        self.assertEqual(view["cache_query_tokens"], 300)
        self.assertEqual(view["cache_hit_ratio"], 0.3)
        self.assertTrue(view["cache_usage_complete"])

    def test_partial_cache_usage_is_flagged_and_uses_only_paired_observations(self):
        view = model_server_metrics({"usage": {"model_calls": 3}, "trace": [cache_entry(40, 100),
            {"kind": "model", "error": "timeout"}, {"kind": "model", "response": {
                "usage_metadata": {"input_tokens": 900}}}]})
        self.assertEqual(view["cache_hit_tokens"], 40)
        self.assertEqual(view["cache_query_tokens"], 100)
        self.assertEqual(view["cache_hit_ratio"], 0.4)
        self.assertFalse(view["cache_usage_complete"])
        self.assertEqual(view["cache_measured_model_calls"], 1)

    def test_missing_raw_prompt_count_is_not_filled_by_sdk_default_zero(self):
        view = model_server_metrics({"usage": {"model_calls": 1}, "trace": [{"kind": "model", "response": {
            "response_metadata": {"token_usage": {"completion_tokens": 5,
                "prompt_tokens_details": {"cached_tokens": 0}}},
            "usage_metadata": {"input_tokens": 0, "input_token_details": {"cache_read": 0}}}}]})
        self.assertIsNone(view["cache_hit_tokens"])
        self.assertIsNone(view["cache_query_tokens"])
        self.assertFalse(view["cache_usage_complete"])

    def test_real_zero_hits_and_zero_denominator_remain_distinct_from_missing(self):
        zero_hits = model_server_metrics({"usage": {"model_calls": 1}, "trace": [cache_entry(0, 100)]})
        self.assertEqual(zero_hits["cache_hit_tokens"], 0)
        self.assertEqual(zero_hits["cache_hit_ratio"], 0)
        empty_prompt = model_server_metrics({"usage": {"model_calls": 1}, "trace": [cache_entry(0, 0)]})
        self.assertEqual(empty_prompt["cache_hit_tokens"], 0)
        self.assertIsNone(empty_prompt["cache_hit_ratio"])
        self.assertTrue(empty_prompt["cache_usage_complete"])
        self.assertEqual(empty_prompt["cache_unavailable_reason"], "ZERO_CACHE_QUERY_TOKENS")
        missing = model_server_metrics(None)
        self.assertIsNone(missing["cache_hit_tokens"])
        self.assertIsNone(missing["cache_hit_ratio"])
        self.assertFalse(missing["cache_usage_complete"])
        self.assertEqual(missing["cache_unavailable_reason"], "CACHE_USAGE_NOT_AVAILABLE")

    def test_unobserved_model_calls_make_usage_incomplete(self):
        for total in (None, 2):
            with self.subTest(total=total):
                view = model_server_metrics({"usage": {"model_calls": total}, "trace": [cache_entry(10, 20)]})
                self.assertFalse(view["cache_usage_complete"])


if __name__ == "__main__":
    unittest.main()
