from datetime import datetime

from app.db.models import Paper, Task
from app.research.task_policy import automatic_budget


def resource_error(resource: Paper | Task) -> dict | None:
    if resource.error_code is None:
        return None
    return {
        "code": resource.error_code,
        "message": resource.error_message,
        "details": resource.error_details or {},
    }


def paper_view(paper: Paper) -> dict:
    fields = (
        "id", "title", "original_filename", "content_type", "size_bytes", "sha256",
        "status", "page_count", "parser_version", "created_at", "updated_at",
    )
    from app.sources.arxiv import ArxivPaper

    source = paper.source
    provenance = ArxivPaper(
        **source.source_metadata, provider=source.provider, external_id=source.external_id,
    ).source_view() if source is not None else None
    return {**{name: getattr(paper, name) for name in fields}, "error": resource_error(paper), "source": provenance}


def accepted_view(task: Task) -> dict:
    return {
        **{name: getattr(task, name) for name in (
            "id", "task_type", "workflow_type", "status", "stage", "created_at"
        )},
        "is_mock": task.runner_type == "mock",
    }


def summary_view(task: Task, paper_ids: list) -> dict:
    return {
        **accepted_view(task),
        **{name: getattr(task, name) for name in (
            "question", "updated_at", "started_at", "finished_at"
        )},
        "paper_ids": paper_ids,
        "error": resource_error(task),
    }


def elapsed_ms(start: datetime | None, end: datetime | None) -> int | None:
    if start is None or end is None:
        return None
    duration = end - start
    return duration.days * 86400000 + duration.seconds * 1000 + duration.microseconds // 1000


def task_view(task: Task, paper_ids: list) -> dict:
    total_tokens = None
    if task.input_tokens is not None and task.output_tokens is not None:
        total_tokens = task.input_tokens + task.output_tokens
    search = (task.review_state or {}).get("search", {})
    selection = search.get("selection", {}).get("diagnostic", {})
    outcome = search.get("outcome", {})
    retrieval = None
    if task.run_config.get("search_policy"):
        columns = {column["key"]: column["label"] for column in task.run_config.get("review_policy", {}).get("columns", [])}
        titles = {paper["paper_id"]: paper["paper_title"] for paper in (task.review_state or {}).get("source_snapshot", {}).get("papers", [])}
        selected_ids = {str(paper_id) for paper_id in paper_ids}
        missing_papers = [{"paper_id": item["paper_id"], "paper_title": titles.get(item["paper_id"], ""),
            "columns": [columns.get(key, key) for key in item["columns"]]} for item in outcome.get("papers", [])
            if item["columns"] and item["paper_id"] in selected_ids]
        retrieval = {"status": outcome.get("status", selection.get("status", "pending")),
            "expansion_degraded": bool(search.get("query", {}).get("degraded")),
            "selected_chunks": selection.get("selected_chunks", 0), "lexical_matches": selection.get("lexical_matches", 0),
            "missing_aspects": outcome.get("missing_aspects", []), "papers": missing_papers}
    return {
        **summary_view(task, paper_ids),
        "result_format": "agent-v1" if task.runner_type == "agent" else "legacy",
        "agent_input": task.agent_input if task.runner_type == "agent" else None,
        "budget_mode": "automatic" if automatic_budget(task) else "manual",
        "budget": {name: getattr(task, name) for name in (
            "max_steps", "max_tokens", "timeout_seconds"
        )},
        "versions": {name: getattr(task, name) for name in (
            "model_id", "workflow_version", "prompt_version", "dataset_version"
        )},
        "stats": {
            "usage_estimated": bool((task.review_state or {}).get("usage_estimated", False)),
            "queue_ms": elapsed_ms(task.created_at, task.started_at),
            "execution_ms": elapsed_ms(task.started_at, task.finished_at),
            "end_to_end_ms": elapsed_ms(task.created_at, task.finished_at),
            "total_tokens": total_tokens,
            **{name: getattr(task, name) for name in (
                "input_tokens", "output_tokens", "model_calls", "tool_calls"
            )},
        },
        "last_event_seq": task.last_event_seq,
        "retrieval": retrieval,
    }
