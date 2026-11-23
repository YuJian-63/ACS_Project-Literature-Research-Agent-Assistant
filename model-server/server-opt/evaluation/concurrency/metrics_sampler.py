"""Collect a small Prometheus time series while requests are in flight."""
from datetime import datetime, timezone
import math
import re
from threading import Event, Thread

from model_client import ServiceError


GAUGES = ("num_requests_running", "num_requests_waiting", "kv_cache_usage_perc")
COUNTERS = ("prefix_cache_queries_total", "prefix_cache_hits_total", "num_preemptions_total",
            "request_queue_time_seconds_count", "request_queue_time_seconds_sum",
            "request_prefill_time_seconds_count", "request_prefill_time_seconds_sum",
            "request_prefill_kv_computed_tokens_count", "request_prefill_kv_computed_tokens_sum")
METRIC_LINE = re.compile(r"^vllm:(\w+)(\{.*?\})?\s+(\S+)")


def selected_metrics(text):
    result = {}
    for line in text.splitlines():
        match = METRIC_LINE.match(line)
        if match and match[1] in GAUGES + COUNTERS:
            value = float(match[3])
            if math.isfinite(value):
                result.setdefault(match[1], {})[match[2] or ""] = value
    return result


def metrics_summary(samples):
    valid = [sample["values"] for sample in samples if sample.get("values")]
    peaks = {}
    for metric in GAUGES:
        values = [sample[metric].values() for sample in valid if metric in sample]
        # Request counts sum across engine labels. Occupancy is the busiest engine.
        reducer = max if metric == "kv_cache_usage_perc" else sum
        peaks[metric] = max((reducer(series) for series in values), default=None)
    deltas = dict.fromkeys(COUNTERS)
    if len(valid) >= 2:
        for metric in COUNTERS:
            start = valid[0].get(metric, {})
            end = valid[-1].get(metric, {})
            if start and start.keys() == end.keys() and all(end[key] >= start[key] for key in start):
                deltas[metric] = sum(end[key] - start[key] for key in start)
    hits = deltas["prefix_cache_hits_total"]
    queries = deltas["prefix_cache_queries_total"]
    queued = deltas["request_queue_time_seconds_count"]
    queue_time = deltas["request_queue_time_seconds_sum"]
    return {"samples": len(valid), "errors": [s["error"] for s in samples if "error" in s][:3],
            "peak_observed": peaks, "counter_deltas": deltas,
            "prefix_cache_hit_fraction": hits / queries if hits is not None and queries else None,
            "mean_queue_time_s": queue_time / queued if queue_time is not None and queued else None}


def boundary_metrics_summary(samples):
    result = metrics_summary(samples)
    result["peak_observed"] = None
    result["gauge_scope"] = "Boundary snapshots only; no time-series or peak measurement"
    return result


class MetricsSampler:
    def __init__(self, client, interval):
        self.client, self.interval = client, interval
        self.samples = []
        self.stop = Event()
        self.worker = Thread(target=self.collect, daemon=True)

    def sample(self, stage):
        row = {"timestamp_utc": datetime.now(timezone.utc).isoformat(), "stage": stage}
        try:
            row["values"] = selected_metrics(self.client.get_text("metrics", server_root=True))
        except (ServiceError, ValueError) as exc:
            row["error"] = str(exc)
        self.samples.append(row)

    def collect(self):
        # The before snapshot serves as the initial sample.
        while not self.stop.wait(self.interval):
            self.sample("during")

    def __enter__(self):
        self.sample("before")
        self.worker.start()
        return self

    def __exit__(self, *_exc):
        self.stop.set()
        self.worker.join()
        self.sample("after")
