from sqlalchemy import select

from app.agent_bridge.model_telemetry import CACHE_FIELDS, FIELDS, clean_capture, extract_cache_metrics, mapping
from app.db.models import TaskEvaluation
from app.evaluations.contracts import WEIGHTS


def evaluation_metrics(row, settings):
    report = mapping(row.report) if row is not None and row.status == "succeeded" else {}
    dimensions = mapping(report.get("dimensions"))
    config = row.config if row is not None else {}
    return {"status": row.status if row is not None else "not_requested",
        "enabled": settings.evaluation_enabled, "configured": settings.evaluation_configured,
        "evaluation_id": row.id if row is not None else None,
        **{key: config.get(key) for key in ("provider", "model", "rubric_version", "prompt_version")},
        "error_code": row.error_code if row is not None else None,
        "assessment": report.get("assessment"), "overall_score": report.get("overall_score"),
        "score_max": 5, "overall_score_max": 100, "weights": config.get("weights", WEIGHTS),
        "dimensions": {key: {"score": mapping(dimensions.get(key)).get("score"),
            "reason": mapping(dimensions.get(key)).get("reason")} for key in WEIGHTS}}


def agent_metrics(result):
    usage = mapping(mapping(result).get("usage"))
    return {"available": bool(usage), "unavailable_reason": None if usage else "AGENT_USAGE_NOT_AVAILABLE",
        **{key: usage.get(key) for key in ("agent_steps", "model_calls", "tool_calls", "input_tokens",
            "output_tokens", "total_tokens", "token_usage_complete")}}


def model_server_metrics(result):
    result = mapping(result)
    trace = result.get("trace")
    entries = [entry for entry in trace if isinstance(entry, dict) and entry.get("kind") == "model"] if isinstance(trace, list) else []
    requests = []
    latest_gpus = {}
    for call_index, entry in enumerate(entries, 1):
        response = mapping(entry.get("response"))
        metadata = mapping(response.get("response_metadata"))
        capture = clean_capture(metadata.get("server_metrics"))
        view = {"call_index": call_index, "available": False, "request_id": None,
            **dict.fromkeys((*FIELDS, *CACHE_FIELDS)), "sources": {}, "gpus": [], "gpu_sampled_at": None,
            "unavailable_reason": "MODEL_REQUEST_FAILED" if entry.get("error") else "SERVER_METRICS_NOT_RETURNED"}
        if capture is not None:
            view.update({key: value for key, value in capture.items() if key != "schema"})
            for gpu in view["gpus"]:
                latest_gpus[gpu["uuid"]] = {**gpu, "call_index": call_index, "sampled_at": view["gpu_sampled_at"]}
        if view["cache_hit_tokens"] is None:
            cached = extract_cache_metrics({"usage": metadata.get("token_usage"),
                "usage_metadata": response.get("usage_metadata")})
            if cached is not None:
                view.update({key: cached[key] for key in CACHE_FIELDS})
                view["sources"].update(cached["sources"])
        view["available"] = any(view[key] is not None for key in (*FIELDS, *CACHE_FIELDS)) or any(
            gpu["utilization_percent"] is not None for gpu in view["gpus"])
        if view["available"]:
            view["unavailable_reason"] = None
        requests.append(view)
    total = mapping(result.get("usage")).get("model_calls")
    observed = len(requests)
    measured = sum(row["available"] for row in requests)
    cache_requests = [row for row in requests if row["cache_hit_tokens"] is not None]
    cache_hits = sum(row["cache_hit_tokens"] for row in cache_requests) if cache_requests else None
    cache_queries = sum(row["cache_query_tokens"] for row in cache_requests) if cache_requests else None
    cache_complete = observed > 0 and total == observed and len(cache_requests) == observed
    complete = observed > 0 and total == observed and all(
        row["ttft_ms"] is not None and (row["tpot_ms"] is not None or row["mean_itl_ms"] is not None)
        and row["tokens_per_second"] is not None and row["gpus"]
        and all(gpu["utilization_percent"] is not None for gpu in row["gpus"]) for row in requests) and cache_complete
    aggregates = {}
    for key in FIELDS:
        values = [row[key] for row in requests if row[key] is not None]
        sources = {row["sources"][key] for row in requests if row[key] is not None}
        same_source = len(sources) == 1
        aggregates[key] = {"mean": sum(value / len(values) for value in values) if values and same_source else None,
            "samples": len(values), "source": next(iter(sources)) if same_source else None,
            "unavailable_reason": "NO_SAMPLES" if not values else "MIXED_SOURCES" if not same_source else None}
    return {"status": "available" if complete else "partial" if measured else "unavailable",
        "unavailable_reason": None if measured else "SERVER_METRICS_NOT_AVAILABLE",
        "model_calls_total": total, "observed_model_calls": observed, "measured_model_calls": measured,
        "cache_hit_tokens": cache_hits, "cache_query_tokens": cache_queries,
        "cache_hit_ratio": cache_hits / cache_queries if cache_queries else None,
        "cache_usage_complete": cache_complete, "cache_measured_model_calls": len(cache_requests),
        "cache_unavailable_reason": "CACHE_USAGE_NOT_AVAILABLE" if not cache_requests else (
            "ZERO_CACHE_QUERY_TOKENS" if not cache_queries else None),
        "aggregation": "arithmetic_mean_of_available_requests_with_identical_source",
        **aggregates, "gpus": list(latest_gpus.values()), "requests": requests,
        "gpu_scope": "allocated_device_snapshot_at_response_completion_including_other_processes"}


def task_metrics(session, task, run, settings):
    evaluation = session.scalar(select(TaskEvaluation).where(TaskEvaluation.task_id == task.id)
        .order_by(TaskEvaluation.created_at.desc(), TaskEvaluation.id.desc()).limit(1))
    result = run.result if run is not None else None
    return {"schema_version": "task-metrics-v1", "evaluation": evaluation_metrics(evaluation, settings),
        "agent": agent_metrics(result), "model_server": model_server_metrics(result)}
