import math
import re
from functools import wraps

SCHEMA = "backend-model-metrics-v1"
FIELDS = ("ttft_ms", "tpot_ms", "mean_itl_ms", "tokens_per_second")
NATIVE_FIELDS = {
    "ttft_ms": ("time_to_first_token_ms", "ttft_ms"),
    "tpot_ms": ("time_per_output_token_ms", "tpot_ms"),
    "mean_itl_ms": ("mean_itl_ms", "mean_inter_token_latency_ms"),
    "tokens_per_second": ("tokens_per_second", "output_tokens_per_second"),
}
SERVER_FIELDS = {
    "ttft_ms": "server_time_to_first_output_event_ms",
    "tpot_ms": "server_mean_time_per_output_token_ms",
    "tokens_per_second": "server_output_tokens_per_second",
}
CACHE_SOURCE_PAIRS = (
    ("usage.prompt_tokens_details.cached_tokens", "usage.prompt_tokens"),
    ("metrics.telemetry.request.cache_hit_tokens", "metrics.telemetry.request.cache_query_tokens"),
    ("usage_metadata.input_token_details.cache_read", "usage_metadata.input_tokens"),
)
CACHE_FIELDS = ("cache_hit_tokens", "cache_query_tokens", "cache_hit_ratio")


def cache_usage(hits, queries, hit_source, query_source):
    if (type(hits) is not int or type(queries) is not int or not 0 <= hits <= queries
        or (hit_source, query_source) not in CACHE_SOURCE_PAIRS):
        return None
    return {"cache_hit_tokens": hits, "cache_query_tokens": queries,
        "cache_hit_ratio": hits / queries if queries else None,
        "sources": {"cache_hit_tokens": hit_source, "cache_query_tokens": query_source}}


def extract_cache_metrics(payload):
    payload = mapping(payload)
    usage = mapping(payload.get("usage"))
    request = mapping(mapping(mapping(payload.get("metrics")).get("telemetry")).get("request"))
    sdk_usage = {} if usage else mapping(payload.get("usage_metadata"))
    candidates = (
        (mapping(usage.get("prompt_tokens_details")).get("cached_tokens"), usage.get("prompt_tokens")),
        (request.get("cache_hit_tokens"), request.get("cache_query_tokens")),
        (mapping(sdk_usage.get("input_token_details")).get("cache_read"), sdk_usage.get("input_tokens")),
    )
    for counts, sources in zip(candidates, CACHE_SOURCE_PAIRS):
        result = cache_usage(*counts, *sources)
        if result is not None:
            return result
    return None


def number(value, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        valid = math.isfinite(value) and value >= 0 and (maximum is None or value <= maximum)
    except OverflowError:
        return None
    return value if valid else None


def mapping(value):
    return value if isinstance(value, dict) else {}


def identifier(value):
    return value if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", value) else None


def timestamp(value):
    from datetime import datetime

    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value if parsed.tzinfo is not None else None
    except ValueError:
        return None


def clean_capture(capture):
    capture = mapping(capture)
    if capture.get("schema") != SCHEMA:
        return None
    result = {"schema": SCHEMA, "request_id": identifier(capture.get("request_id")),
        **{key: number(capture.get(key)) for key in FIELDS}, **dict.fromkeys(CACHE_FIELDS), "sources": {},
        "gpu_sampled_at": timestamp(capture.get("gpu_sampled_at")), "gpus": []}
    sources = mapping(capture.get("sources"))
    for key in FIELDS:
        allowed = {"metrics." + name for name in NATIVE_FIELDS[key]}
        if key in SERVER_FIELDS:
            allowed.add("metrics.telemetry.request." + SERVER_FIELDS[key])
        if result[key] is not None and isinstance(sources.get(key), str) and sources[key] in allowed:
            result["sources"][key] = sources[key]
        else:
            result[key] = None
    cached = cache_usage(capture.get("cache_hit_tokens"), capture.get("cache_query_tokens"),
        sources.get("cache_hit_tokens"), sources.get("cache_query_tokens"))
    if cached is not None:
        result.update({key: cached[key] for key in CACHE_FIELDS})
        result["sources"].update(cached["sources"])
    rows = capture.get("gpus")
    seen = set()
    for row in rows if isinstance(rows, list) else []:
        row = mapping(row)
        uuid = identifier(row.get("uuid"))
        if uuid and uuid.startswith("GPU-") and uuid not in seen:
            result["gpus"].append({"uuid": uuid, "utilization_percent": number(row.get("utilization_percent"), 100)})
            seen.add(uuid)
    return result


def extract_server_metrics(payload):
    native = mapping(mapping(payload).get("metrics"))
    cached = extract_cache_metrics(payload)
    if not native and cached is None:
        return None
    telemetry = mapping(native.get("telemetry"))
    request = mapping(telemetry.get("request"))
    capture = {"schema": SCHEMA, "request_id": telemetry.get("request_id"), "sources": {}}
    for key, aliases in NATIVE_FIELDS.items():
        capture[key] = None
        for alias in aliases:
            value = number(native.get(alias))
            if value is not None:
                capture[key] = value
                capture["sources"][key] = "metrics." + alias
                break
        fallback = SERVER_FIELDS.get(key)
        if capture[key] is None and fallback and number(request.get(fallback)) is not None:
            capture[key] = request[fallback]
            capture["sources"][key] = "metrics.telemetry.request." + fallback
    snapshot = mapping(telemetry.get("gpu_snapshot"))
    capture["gpu_sampled_at"] = snapshot.get("sampled_at_utc")
    rows = snapshot.get("gpus")
    capture["gpus"] = [{"uuid": row.get("uuid"), "utilization_percent": row.get("gpu_utilization_percent")}
        for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
    if cached is not None:
        capture.update({key: cached[key] for key in CACHE_FIELDS})
        capture["sources"].update(cached["sources"])
    return clean_capture(capture)


def install():
    from langchain_openai import ChatOpenAI

    original = ChatOpenAI._create_chat_result
    if getattr(original, "_backend_metrics_capture", False):
        return

    @wraps(original)
    def create_chat_result(self, response, *args, **kwargs):
        result = original(self, response, *args, **kwargs)
        try:
            payload = response if isinstance(response, dict) else response.model_dump()
            capture = extract_server_metrics(payload)
            if capture is not None:
                for generation in result.generations:
                    generation.message.response_metadata["server_metrics"] = capture
        except Exception:
            pass
        return result

    create_chat_result._backend_metrics_capture = True
    ChatOpenAI._create_chat_result = create_chat_result
