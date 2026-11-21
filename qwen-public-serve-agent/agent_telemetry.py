"""Add scoped telemetry to native chat responses without buffering generated text."""

import json
import math
import os
from pathlib import Path
import re
import time
from datetime import datetime, timezone

SCHEMA = "qwen-agent-telemetry-v1"
SERVICE_METRICS = (
    "vllm:prefix_cache_queries_total", "vllm:prefix_cache_hits_total",
    "vllm:request_prefill_kv_computed_tokens_sum", "vllm:request_prefill_time_seconds_sum",
    "vllm:num_preemptions_total", "vllm:kv_cache_usage_perc",
)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def number(value):
    return value if type(value) in (int, float) and math.isfinite(value) else None


def divide(numerator, denominator):
    return numerator / denominator if numerator is not None and denominator is not None and denominator > 0 else None


class EventBuffer:
    """Split complete SSE frames, including frames split across ASGI body writes."""

    def __init__(self):
        self.pending = b""

    def feed(self, data, final=False):
        self.pending += data
        frames = []
        while match := re.search(br"\r?\n\r?\n", self.pending):
            frames.append(self.pending[:match.end()])
            self.pending = self.pending[match.end():]
        if final and self.pending:
            frames.append(self.pending)
            self.pending = b""
        return frames


def event_json(frame):
    payload = b"\n".join(line[5:].lstrip(b" ") for line in frame.splitlines() if line.startswith(b"data:"))
    if not payload or payload == b"[DONE]":
        return None
    try:
        parsed = json.loads(payload)
        return parsed if isinstance(parsed, dict) else None
    except (ValueError, UnicodeError):
        return None


def has_generated_output(choice):
    delta = choice.get("delta") or {}
    return bool(delta.get("content") or delta.get("reasoning") or delta.get("reasoning_content")
                or any(c.get("function", {}).get("name") or c.get("function", {}).get("arguments")
                       for c in delta.get("tool_calls", [])))


def request_metrics(usage, native, started, first, last, finished, single_stream=True):
    prompt = number(usage.get("prompt_tokens"))
    output = number(usage.get("completion_tokens"))
    cached = number((usage.get("prompt_tokens_details") or {}).get("cached_tokens"))
    cache_valid = prompt is not None and cached is not None and 0 <= cached <= prompt
    return {
        "scope": "one HTTP chat request, server-side only",
        "client_end_to_end_latency_ms": None,
        "client_latency_note": "Client receive timestamps and network latency cannot be measured by the server",
        "server_elapsed_ms": (finished - started) * 1000,
        "server_elapsed_scope": "ASGI request entry to native final response/usage event, before telemetry collection",
        "server_time_to_first_output_event_ms": (first - started) * 1000 if first is not None else None,
        "server_mean_time_per_output_token_ms": (
            (last - first) * 1000 / (output - 1)
            if single_stream and first is not None and last is not None and output is not None and output > 1 else None
        ),
        "server_output_tokens_per_second": divide(output, finished - started),
        "input_tokens": prompt, "output_tokens": output, "total_tokens": number(usage.get("total_tokens")),
        "cache_hit_tokens": cached if cache_valid else None,
        "cache_query_tokens": prompt if cache_valid else None,
        "cache_query_scope": "Initial local-APC lookup denominator equals prompt tokens in this deployment; no external KV connector",
        "prefix_cache_hit_ratio": divide(cached, prompt) if cache_valid else None,
        "prefill_computed_tokens": prompt - cached if cache_valid else None,
        "prefill_computed_tokens_source": "usage.prompt_tokens minus usage.prompt_tokens_details.cached_tokens; local prefill accounting",
        "prefill_computed_tokens_scope": "Uncached prompt-token accounting, not FLOPs or a count of repeated work after preemption",
        "prefill_time_ms": number(native.get("time_to_first_token_ms")) if single_stream else None,
        "prefill_time_scope": "vLLM first scheduled to first generated token, includes interruptions; not pure CUDA kernel time",
        "streaming_observation_supported": first is not None,
    }


class ResourceReader:
    def __init__(self):
        self.module = None
        self.handles = []
        self.error = None
        uuids = [v.strip() for v in os.getenv("QWEN_TELEMETRY_GPU_UUIDS", "").split(",") if v.strip()]
        try:
            if len(uuids) != 2 or len(set(uuids)) != 2 or not all(v.startswith("GPU-") for v in uuids):
                raise ValueError("Two allocated GPU UUIDs are required; no other devices will be queried")
            from vllm.utils.import_utils import import_pynvml

            self.module = import_pynvml()
            self.module.nvmlInit()
            self.handles = [(uuid, self.module.nvmlDeviceGetHandleByUUID(uuid)) for uuid in uuids]
        except Exception as exc:
            self.error = type(exc).__name__ + ": " + str(exc)

    def snapshot(self):
        result = {"scope": "whole allocated devices at response completion, may include other processes",
                  "sampled_at_utc": utc_now(), "is_request_average_or_peak": False,
                  "utilization_scope": "NVML driver sampling window, not per-request GPU utilization", "gpus": []}
        if self.error:
            result["error"] = self.error
            return result
        for uuid, handle in self.handles:
            try:
                memory = self.module.nvmlDeviceGetMemoryInfo(handle)
                row = {"uuid": uuid, "memory_used_mib": memory.used / 1048576,
                       "memory_total_mib": memory.total / 1048576, "memory_free_mib": memory.free / 1048576}
                try:
                    row["gpu_utilization_percent"] = self.module.nvmlDeviceGetUtilizationRates(handle).gpu
                except Exception as exc:
                    row["gpu_utilization_percent"] = None
                    row["utilization_error"] = type(exc).__name__
                result["gpus"].append(row)
            except Exception as exc:
                result["gpus"].append({"uuid": uuid, "error": type(exc).__name__ + ": " + str(exc)})
        return result


def service_cache_snapshot():
    try:
        from vllm.v1.metrics.prometheus import get_prometheus_registry

        values = {name: [] for name in SERVICE_METRICS}
        for family in get_prometheus_registry().collect():
            for sample in family.samples:
                if sample.name in values and number(sample.value) is not None:
                    values[sample.name].append(sample.value)
        reduced = {name.removeprefix("vllm:"): (max(series) if name.endswith("usage_perc") else sum(series))
                   if series else None for name, series in values.items()}
        reduced["prefix_cache_hit_ratio"] = divide(reduced["prefix_cache_hits_total"], reduced["prefix_cache_queries_total"])
        return {"scope": "vLLM instance cumulative counters and current KV gauge; asynchronous updates may lag",
                "sampled_at_utc": utc_now(), "values": reduced,
                "kv_cache_usage_scale": "0 to 1; not GPU memory utilization", "is_request_delta": False}
    except Exception as exc:
        return {"scope": "vLLM instance", "values": None, "error": type(exc).__name__ + ": " + str(exc)}


class AgentTelemetryMiddleware:
    """Native ASGI middleware; passthrough all content/tool deltas, enrich final usage."""

    def __init__(self, app):
        self.app = app
        self.resources = ResourceReader()
        self.window_start = None
        self.started = self.completed = self.failed = self.cancelled = self.output_tokens = 0
        path = os.getenv("QWEN_AGENT_TELEMETRY_LOG")
        self.log_path = Path(path) if path else None
        if self.log_path:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
        print("AGENT_TELEMETRY_READY=" + SCHEMA, flush=True)

    def aggregate(self, now):
        seconds = now - self.window_start if self.window_start is not None else None
        return {"scope": "this API process since its first chat request, includes all users and idle gaps",
                "api_process_pid": os.getpid(), "window_seconds": seconds,
                "requests_started": self.started, "requests_completed": self.completed,
                "requests_failed": self.failed, "requests_cancelled_or_interrupted": self.cancelled,
                "requests_per_second": divide(self.completed, seconds),
                "output_tokens_per_second": divide(self.output_tokens, seconds),
                "output_tokens": self.output_tokens,
                "is_fixed_load_benchmark_throughput": False}

    def write_log(self, payload):
        if self.log_path:
            try:
                with self.log_path.open("a", encoding="utf-8") as output:
                    output.write(json.dumps(payload, ensure_ascii=False, allow_nan=False) + "\n")
            except OSError as exc:
                print("AGENT_TELEMETRY_LOG_ERROR=" + type(exc).__name__, flush=True)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") != "POST" or scope.get("path") != "/v1/chat/completions":
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        self.window_start = started if self.window_start is None else self.window_start
        self.started += 1
        parser = EventBuffer()
        body_parts = []
        state = {"stream": False, "json": False, "status": None, "first": None, "last": None,
                 "id": None, "indices": set(), "enriched": False, "finished": False}

        def enrich(payload):
            finished = time.perf_counter()
            usage = payload.get("usage") or {}
            native = payload.get("metrics") or {}
            if not isinstance(native, dict):
                native = {}
            state["enriched"] = True
            self.completed += 1
            self.output_tokens += int(number(usage.get("completion_tokens")) or 0)
            request = request_metrics(usage, native, started, state["first"], state["last"], finished,
                                      len(state["indices"]) <= 1)
            collection_started = time.perf_counter()
            telemetry = {"schema": SCHEMA, "request_id": payload.get("id") or state["id"],
                         "request": request, "service_window": self.aggregate(finished),
                         "service_cache_snapshot": service_cache_snapshot(), "gpu_snapshot": self.resources.snapshot(),
                         "logged_at_utc": utc_now()}
            telemetry["collection_overhead_ms"] = (time.perf_counter() - collection_started) * 1000
            payload["metrics"] = dict(native, telemetry=telemetry)
            self.write_log(telemetry)
            return payload

        async def wrapped_send(message):
            if message["type"] == "http.response.start":
                state["status"] = message["status"]
                headers = list(message.get("headers", []))
                content_type = next((v.lower() for k, v in headers if k.lower() == b"content-type"), b"")
                if 200 <= message["status"] < 300:
                    state["stream"] = b"text/event-stream" in content_type
                    state["json"] = b"application/json" in content_type
                    if state["stream"] or state["json"]:
                        message = dict(message, headers=[(k, v) for k, v in headers if k.lower() != b"content-length"])
                await send(message)
                return
            if message["type"] != "http.response.body":
                await send(message)
                return
            data, final = message.get("body", b""), not message.get("more_body", False)
            if state["stream"]:
                for frame in parser.feed(data, final=final):
                    payload = event_json(frame)
                    if payload is not None:
                        state["id"] = payload.get("id") or state["id"]
                        for choice in payload.get("choices", []):
                            state["indices"].add(choice.get("index", 0))
                            if has_generated_output(choice):
                                arrived = time.perf_counter()
                                state["first"] = arrived if state["first"] is None else state["first"]
                                state["last"] = arrived
                        if payload.get("usage") is not None and not payload.get("choices") and not state["enriched"]:
                            try:
                                frame = b"data: " + json.dumps(enrich(payload), ensure_ascii=False, allow_nan=False).encode() + b"\n\n"
                            except Exception as exc:
                                print("AGENT_TELEMETRY_RESPONSE_ERROR=" + type(exc).__name__, flush=True)
                    await send({"type": "http.response.body", "body": frame, "more_body": True})
                if final:
                    await send({"type": "http.response.body", "body": b"", "more_body": False})
            elif state["json"]:
                body_parts.append(data)
                if final:
                    raw = b"".join(body_parts)
                    try:
                        payload = json.loads(raw)
                        if isinstance(payload, dict) and payload.get("usage") is not None and isinstance(payload.get("choices"), list):
                            state["indices"] = {c.get("index", 0) for c in payload["choices"]}
                            raw = json.dumps(enrich(payload), ensure_ascii=False, allow_nan=False).encode()
                    except Exception as exc:
                        print("AGENT_TELEMETRY_RESPONSE_ERROR=" + type(exc).__name__, flush=True)
                    await send({"type": "http.response.body", "body": raw, "more_body": False})
            else:
                await send(message)
            if final:
                state["finished"] = True

        try:
            await self.app(scope, receive, wrapped_send)
        finally:
            if not state["enriched"]:
                if state["status"] is not None and state["status"] >= 400:
                    self.failed += 1
                elif not state["finished"]:
                    self.cancelled += 1
                else:
                    self.failed += 1
                self.write_log({"schema": SCHEMA, "request_id": state["id"], "http_status": state["status"],
                                "response_completed": state["finished"], "metrics_available": False,
                                "scope": "request error, interrupted stream, or no final usage; no metrics fabricated",
                                "logged_at_utc": utc_now()})
