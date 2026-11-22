import hashlib
import json
import re
from uuid import UUID

from sqlalchemy import cast, func, select
from sqlalchemy.dialects.postgresql import JSONPATH
from sqlalchemy.exc import IntegrityError

from app.agent_bridge.submission import create_research_task, ensure_agent_ready
from app.agent_bridge.results import ARXIV_SOURCE
from app.api.agent_research_schemas import AgentResearchCreate
from app.db.models import AgentRun, Paper, PaperSource, Task, TaskPaper
from app.db.ownership import check_task_capacity, lock_active_user
from app.errors import APIError
from app.tasks.service import validate_idempotency_key

RESEARCH_INTERFACE = "agent-research-v1"


def research_filters(user_id: UUID):
    return (
        Task.user_id == user_id,
        Task.runner_type == "agent",
        Task.run_config["interface"].as_string() == RESEARCH_INTERFACE,
    )


def get_research(session, task_id: UUID, user_id: UUID, *, lock: bool = False):
    query = select(Task).where(Task.id == task_id, *research_filters(user_id))
    task = session.scalar(query.with_for_update() if lock else query)
    if task is None:
        raise APIError(404, "TASK_NOT_FOUND", "研究记录不存在")
    return task


def research_references(session, task_ids: list[UUID], user_id: UUID):
    result = {task_id: [] for task_id in task_ids}
    if task_ids:
        rows = session.execute(
            select(TaskPaper.task_id, Paper.id, Paper.title)
            .join(Paper, (Paper.id == TaskPaper.paper_id) & (Paper.user_id == TaskPaper.user_id))
            .where(TaskPaper.task_id.in_(task_ids), TaskPaper.user_id == user_id, TaskPaper.selection_order.is_not(None))
            .order_by(TaskPaper.selection_order)
        )
        for task_id, paper_id, title in rows:
            result[task_id].append({"id": paper_id, "title": title})
    return result


def history_papers(session, selected, user_id):
    papers = {task: {p["id"]: p for p in refs} for task, refs in selected.items()}
    if not papers:
        return {}
    discovered = session.execute(
        select(TaskPaper.task_id, Paper.id, Paper.title)
        .join(Paper, Paper.id == TaskPaper.paper_id)
        .where(TaskPaper.task_id.in_(papers), TaskPaper.user_id == user_id, TaskPaper.selection_order.is_(None))
        .order_by(Paper.title, Paper.id)
    )
    for task, paper_id, title in discovered:
        papers[task][paper_id] = {"id": paper_id, "title": title}

    # Resolve saved sources against today's library, including imports made after the run.
    external = []
    for task, sources in session.execute(
        select(AgentRun.task_id, AgentRun.result["sources"]).where(AgentRun.task_id.in_(papers))
    ):
        for source in sources or []:
            match = ARXIV_SOURCE.fullmatch(source["source_id"])
            if not match:
                continue
            hint = source.get("version")
            version = match["version"]
            if hint is not None:
                hinted = "v" + str(hint).removeprefix("v")
                version = hinted if version in (None, hinted) else None
            external_id = match["base"] + version if version else None
            external.append((task, source, external_id, match["sha"] or ""))
    if external:
        imports = session.execute(
            select(PaperSource.external_id, Paper.id, Paper.title, Paper.sha256)
            .join(Paper, Paper.id == PaperSource.paper_id)
            .where(PaperSource.user_id == user_id, PaperSource.provider == "arxiv",
                PaperSource.external_id.in_({external_id for _, _, external_id, _ in external if external_id}))
        )
        by_version = {row.external_id: row for row in imports}
        untitled = []
        for task, source, external_id, digest in external:
            paper = by_version.get(external_id)
            if paper and paper.sha256.startswith(digest):
                papers[task][paper.id] = {"id": paper.id, "title": paper.title}
            else:
                title = source["title"].strip() if isinstance(source.get("title"), str) else ""
                ref = {**source, "id": None, "title": title or source["paper_id"]}
                papers[task][source["source_id"]] = ref
                base = source["paper_id"].removeprefix("arxiv:")
                if not title or re.fullmatch(r"(?:arxiv:\s*)?" + re.escape(base) + r"(?:v\d+|@[\da-f]{12})?", title, re.I):
                    untitled.append((task, ref, base, external_id))

        if untitled:
            # Older PDFs often have no title metadata. Only read the search hits from their trace.
            hits_path = '$.trace[*] ? (@.kind == "tool" && @.name == "search_papers").observation.results[*]'
            hits = func.jsonb_path_query_array(AgentRun.result, cast(hits_path, JSONPATH))
            titles = {}
            task_ids = {task for task, *_ in untitled}
            for task, results in session.execute(select(AgentRun.task_id, hits).where(AgentRun.task_id.in_(task_ids))):
                for hit in results:
                    if not isinstance(hit, dict):
                        continue
                    candidate, title = hit.get("source"), hit.get("title")
                    if not isinstance(candidate, str) or not isinstance(title, str):
                        continue
                    title = title.strip().removeprefix(f"[{candidate}]").strip()
                    if title and title.lower() not in (candidate, "arxiv:" + candidate):
                        titles.setdefault((task, candidate), title)
            for task, ref, base, external_id in untitled:
                ref["title"] = titles.get((task, external_id)) or titles.get((task, base)) or ref["title"]
    return {task: list(by_id.values()) for task, by_id in papers.items()}


def research_request_hash(request: AgentResearchCreate) -> str:
    payload = {"interface": RESEARCH_INTERFACE, **request.model_dump(mode="json")}
    if request.research and not request.research.model_dump(exclude_defaults=True):
        payload.pop("research", None)  # Match default requests from older browser sessions.
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False).encode("utf-8")).hexdigest()


def _replay(task, digest):
    if task.request_hash != digest or task.run_config.get("interface") != RESEARCH_INTERFACE:
        raise APIError(409, "IDEMPOTENCY_CONFLICT", "该幂等键已用于不同请求")
    return {"task_id": task.id, "status": task.status}, True


def submit_research(sessions, settings, request: AgentResearchCreate, key: str | None, *, user_id: UUID):
    validate_idempotency_key(key)
    digest = research_request_hash(request)
    try:
        with sessions.begin() as session:
            lock_active_user(session, user_id)
            if key is not None:
                existing = session.scalar(select(Task).where(Task.user_id == user_id, Task.idempotency_key == key))
                if existing is not None:
                    return _replay(existing, digest)
            ensure_agent_ready(settings, unavailable_code="AGENT_NOT_CONNECTED",
                unavailable_message="研究服务暂未连接，请稍后再试。")
            check_task_capacity(session, user_id, settings.user_active_tasks, settings.user_daily_tasks)
            rows = list(session.scalars(select(Paper).where(
                Paper.user_id == user_id, Paper.id.in_(request.paper_ids),
            ).order_by(Paper.id).with_for_update()))
            by_id = {paper.id: paper for paper in rows}
            missing = [paper_id for paper_id in request.paper_ids if paper_id not in by_id]
            if missing:
                raise APIError(404, "PAPER_NOT_FOUND", "部分论文不存在", {
                    "missing_paper_ids": [str(paper_id) for paper_id in missing],
                })
            papers = [by_id[paper_id] for paper_id in request.paper_ids]
            if any(paper.status not in {"uploaded", "processing", "ready"} for paper in papers):
                raise APIError(409, "PAPER_NOT_READY", "选定论文尚不可用于执行任务")
            accepted = create_research_task(session, settings, request, papers, user_id=user_id,
                key=key, digest=digest, interface=RESEARCH_INTERFACE)
            return {"task_id": accepted["id"], "status": accepted["status"]}, False
    except IntegrityError:
        if key is not None:
            with sessions() as session:
                existing = session.scalar(select(Task).where(Task.user_id == user_id, Task.idempotency_key == key))
                if existing is not None:
                    return _replay(existing, digest)
        raise
