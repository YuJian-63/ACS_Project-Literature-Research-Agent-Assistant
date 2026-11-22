from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.agent_bridge.bundles import manifest_digest
from app.agent_bridge.policy import WORKFLOW_VERSION, build_manifest, build_research_manifest
from app.agent_bridge.transport import create_transport, transport_name
from app.api.schemas import TaskCreate
from app.api.views import accepted_view
from app.config import Settings
from app.db.models import CourseService, SharedModelEndpoint, AgentRun, Paper, Task, TaskEvent, TaskPaper
from app.errors import APIError


def ensure_agent_ready(settings: Settings, *, unavailable_code: str = "RUNNER_NOT_CONFIGURED",
    unavailable_message: str = "Agent 派发尚未启用，请先完成传输配置") -> None:
    if settings.task_runner != "agent" or not settings.agent_dispatch_enabled:
        raise APIError(503, unavailable_code, unavailable_message)
    try:
        create_transport(settings)
    except ValueError:
        raise APIError(503, "RUNNER_NOT_CONFIGURED", "Agent 传输配置不完整，请检查部署配置") from None


def create_agent_task(session: Session, settings: Settings, request: TaskCreate, papers: list[Paper],
    *, user_id: UUID, key: str | None, digest: str) -> dict:
    task_id = uuid4()
    manifest = build_manifest(task_id, uuid4(), request.task_type, request.question,
        [{"paper_id": str(paper.id), "title": paper.title, "sha256": paper.sha256,
            "size_bytes": paper.size_bytes, "page_count": paper.page_count} for paper in papers], settings)
    return _save_agent_task(session, settings, manifest, papers, user_id=user_id, key=key, digest=digest,
        task_type=request.task_type, question=request.question, workflow_type=request.workflow_type)


def create_research_task(session, settings, request, papers, *, user_id, key, digest, interface):
    manifest = build_research_manifest(uuid4(), uuid4(), request.question,
        [{"paper_id": str(paper.id), "title": paper.title, "sha256": paper.sha256,
            "size_bytes": paper.size_bytes, "page_count": paper.page_count} for paper in papers],
        settings, allow_search=request.allow_search, research=request.research)
    if request.research and request.research.model_provider in {"tacc", "custom"}:
        if settings.agent_transport != "tcloud":
            raise APIError(409, "TCLOUD_DISABLED", "课程 TCloud Worker 尚未启用")
        if request.research.model_provider == "custom":
            url = request.research.endpoint_url
            if not url:
                shared = session.get(SharedModelEndpoint, user_id)
                if not shared:
                    raise APIError(409, "MODEL_UNAVAILABLE", "请输入服务地址")
                url = shared.base_url
            manifest.runtime.research = request.research.model_copy(update={"endpoint_url": url})
        else:
            service = session.get(CourseService, 1)
            if not service or service.state != "ready" or service.stop_requested:
                raise APIError(409, "MODEL_UNAVAILABLE", "课程模型尚未就绪，请在模型管理中查看状态")
            manifest.runtime.service_generation = service.generation
        manifest.runtime.context_window = min(manifest.runtime.context_window, 36864)
        manifest.task.max_output_tokens = min(manifest.task.max_output_tokens, 4096)
    return _save_agent_task(session, settings, manifest, papers, user_id=user_id, key=key, digest=digest,
        task_type="review" if len(papers) > 1 else "qa", question=request.question,
        workflow_type="extended" if request.research and request.research.workflow == "extension" else "baseline", interface=interface)


def _save_agent_task(session, settings, manifest, papers, *, user_id, key, digest,
    task_type, question, workflow_type, interface=None):
    task_id = UUID(manifest.task.task_id)
    limits = {name: getattr(manifest.task, name) for name in
        ("max_steps", "max_papers", "timeout_seconds", "max_output_tokens")}
    limits["context_window"] = manifest.runtime.context_window
    run_config = {"budget_mode": "automatic", "agent_limits": limits, "transport": transport_name(settings)}
    if interface is not None:
        run_config.update(interface=interface, allow_search=manifest.task.allow_search)
    task = Task(id=task_id, user_id=user_id, task_type=task_type, question=question,
        workflow_type=workflow_type, runner_type="agent", workflow_version=WORKFLOW_VERSION,
        prompt_version="agent-dispatch-v1", model_id=None,
        run_config=run_config,
        review_state={}, max_steps=manifest.task.max_steps, max_tokens=100000,
        timeout_seconds=int(manifest.task.timeout_seconds), idempotency_key=key, request_hash=digest, last_event_seq=1)
    session.add(task)
    session.flush()
    session.add(AgentRun(task_id=task_id, dispatch_id=manifest.dispatch_id, input_sha256=manifest_digest(manifest),
        manifest=manifest.model_dump(mode="json")))
    session.add_all([TaskPaper(task_id=task_id, user_id=user_id, paper_id=paper.id,
        paper_sha256=paper.sha256, selection_order=index) for index, paper in enumerate(papers)])
    session.add(TaskEvent(task_id=task_id, seq=1, event_type="status", status="queued", stage="queued",
        message="任务已加入 Agent 派发队列", payload={"dispatch_id": str(manifest.dispatch_id)}))
    return accepted_view(task)
