import hashlib
import json
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db.models import Paper, PaperChunk, Task, TaskEvent, TaskPaper
from app.db.ownership import check_task_capacity, lock_active_user
from app.research.retrieval import EvidenceChunk
from app.research.review_policy import WORKFLOW_VERSION, PROMPT_VERSION, build_review_plan
from app.errors import APIError
from app.api.schemas import TaskCreate
from app.api.views import accepted_view


def request_hash(request: TaskCreate, *, automatic_review: bool = False) -> str:
    data = request.model_dump(mode="json")
    if automatic_review:
        data.pop("budget", None)
    canonical = json.dumps(
        data, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_idempotency_key(key: str | None) -> None:
    if key is not None and (not 1 <= len(key) <= 128 or any(not "!" <= char <= "~" for char in key)):
        raise APIError(422, "INVALID_REQUEST", "Idempotency-Key 须为 1—128 个不含空白的 ASCII 可见字符")


def replay(task: Task, digest: str) -> tuple[dict, bool]:
    if task.request_hash != digest:
        raise APIError(409, "IDEMPOTENCY_CONFLICT", "该幂等键已用于不同请求")
    return accepted_view(task), True


def submit_task(
    sessions: sessionmaker[Session], settings: Settings, request: TaskCreate, key: str | None, *, user_id: UUID
) -> tuple[dict, bool]:
    validate_idempotency_key(key)
    digest = request_hash(request)
    try:
        with sessions.begin() as session:
            lock_active_user(session, user_id)
            if key is not None:
                existing = session.scalar(select(Task).where(Task.user_id == user_id, Task.idempotency_key == key))
                if existing is not None:
                    return replay(existing, request_hash(request, automatic_review=existing.workflow_version == WORKFLOW_VERSION))
            check_task_capacity(session, user_id, settings.user_active_tasks, settings.user_daily_tasks)
            if request.workflow_type != "baseline":
                raise APIError(422, "WORKFLOW_NOT_AVAILABLE", "当前阶段仅开放 baseline 工作流")
            runner_type = settings.task_runner
            if runner_type == "langgraph":
                if not settings.real_runner_configured:
                    raise APIError(503, "RUNNER_NOT_CONFIGURED", "真实研究模型尚未配置")
            papers = list(session.scalars(
                select(Paper).where(Paper.user_id == user_id, Paper.id.in_(request.paper_ids)).order_by(Paper.id).with_for_update()
            ))
            missing = sorted(set(request.paper_ids) - {paper.id for paper in papers})
            if missing:
                raise APIError(404, "PAPER_NOT_FOUND", "部分论文不存在", {
                    "missing_paper_ids": [str(paper_id) for paper_id in missing]
                })
            allowed_statuses = {"ready"} if runner_type == "langgraph" else {"uploaded", "ready"}
            if any(paper.status not in allowed_statuses for paper in papers):
                raise APIError(409, "PAPER_NOT_READY", "选定论文尚不可用于执行任务")
            run_config = {"mock_step_delay_seconds": settings.mock_step_delay_seconds}
            budget = request.budget.model_dump()
            review_state = {}
            staged_review = runner_type == "langgraph" and request.task_type == "review"
            if runner_type == "langgraph":
                run_config = {
                    "model_base_url": settings.llm_base_url,
                    "model_thinking_mode": settings.llm_thinking_mode,
                    "model_timeout_seconds": settings.llm_timeout_seconds,
                    "evidence_context_chars": settings.evidence_context_chars,
                }
                if staged_review:
                    groups = {str(paper.id): [] for paper in papers}
                    by_id = {paper.id: paper for paper in papers}
                    chunks = session.scalars(select(PaperChunk).where(PaperChunk.paper_id.in_(by_id)).order_by(PaperChunk.paper_id, PaperChunk.chunk_index))
                    for chunk in chunks:
                        groups[str(chunk.paper_id)].append(EvidenceChunk(
                            chunk_id=str(chunk.id), paper_id=str(chunk.paper_id), paper_title=by_id[chunk.paper_id].title,
                            chunk_index=chunk.chunk_index, page_number=chunk.page_number, content=chunk.content,
                        ))
                    selected = [{"paper_id": str(paper.id), "paper_title": paper.title} for paper in papers]
                    try:
                        plan, evidence = build_review_plan(selected, groups, request.question, settings)
                    except ValueError:
                        raise APIError(422, "REVIEW_CAPACITY_EXCEEDED", "当前综述规模超过服务器处理上限，请缩小研究范围或减少论文数量") from None
                    run_config["review_policy"] = plan
                    review_state = {"evidence": [chunk.model_dump() for chunk in evidence], "units": {}, "usage_estimated": False}
                    budget = {name: plan[name] for name in ("max_steps", "max_tokens", "timeout_seconds")}
                    digest = request_hash(request, automatic_review=True)
            task = Task(
                id=uuid4(), user_id=user_id, task_type=request.task_type, question=request.question,
                workflow_type=request.workflow_type, runner_type=runner_type,
                workflow_version="mock-v1" if runner_type == "mock" else (WORKFLOW_VERSION if staged_review else "langgraph-v1"),
                prompt_version=None if runner_type == "mock" else (PROMPT_VERSION if staged_review else "evidence-v4"),
                model_id=None if runner_type == "mock" else settings.llm_model_id,
                run_config=run_config, review_state=review_state,
                **budget, idempotency_key=key, request_hash=digest,
                last_event_seq=1,
            )
            session.add(task)
            session.flush()
            session.add_all([
                TaskPaper(task_id=task.id, user_id=user_id, paper_id=paper.id, paper_sha256=paper.sha256, selection_order=order)
                for order, paper in enumerate(papers)
            ])
            session.add(TaskEvent(
                task_id=task.id, seq=1, event_type="status", status="queued", stage="queued",
                message="任务已加入队列", payload={},
            ))
            result = accepted_view(task)
        return result, False
    except IntegrityError:
        if key is not None:
            with sessions.begin() as session:
                existing = session.scalar(select(Task).where(Task.user_id == user_id, Task.idempotency_key == key))
                if existing is not None:
                    return replay(existing, request_hash(request, automatic_review=existing.workflow_version == WORKFLOW_VERSION))
        raise


def get_task(session: Session, task_id: UUID, user_id: UUID) -> Task:
    task = session.scalar(select(Task).where(Task.id == task_id, Task.user_id == user_id))
    if task is None:
        raise APIError(404, "TASK_NOT_FOUND", "任务不存在")
    return task


def selected_papers(session: Session, task_ids: list[UUID]) -> dict[UUID, list[UUID]]:
    result = {task_id: [] for task_id in task_ids}
    if task_ids:
        rows = session.execute(
            select(TaskPaper.task_id, TaskPaper.paper_id)
            .where(TaskPaper.task_id.in_(task_ids)).order_by(TaskPaper.paper_id)
        )
        for task_id, paper_id in rows:
            result[task_id].append(paper_id)
    return result
