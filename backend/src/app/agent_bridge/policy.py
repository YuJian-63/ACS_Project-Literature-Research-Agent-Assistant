from uuid import UUID

from app.agent_bridge.contracts import AgentTask, DispatchManifest, ResearchOptions, RuntimeOptions, SourceFile
from app.config import Settings
from app.tasks.language import answer_language_instruction

WORKFLOW_VERSION = "agent-io-v1"


def _source_files(papers):
    return [SourceFile(source_id=f"local:{paper['paper_id']}@{paper['sha256']}",
        paper_id=paper["paper_id"], title=paper["title"], path=f"papers/{paper['paper_id']}.pdf",
        sha256=paper["sha256"], size_bytes=paper["size_bytes"], page_count=paper.get("page_count")) for paper in papers]


def build_research_manifest(task_id: UUID, dispatch_id: UUID, question: str,
    papers: list[dict], settings: Settings, *, allow_search: bool, research: ResearchOptions | None = None) -> DispatchManifest:
    sources = _source_files(papers)
    capacity = min(20, len(sources) + settings.agent_search_max_papers) if allow_search else len(sources)
    instruction = (
        "Research the user's question using original paper evidence. Start with the supplied papers, "
        "if any. Choose the answer format according to the question. "
        "Cite original evidence for factual claims and state evidence gaps. "
        "Use a separate table for requested comparisons and cite the evidence in each row. "
        "Leave comparison_table empty for ordinary single-paper summaries. "
    )
    instruction += ("Search for additional papers only when needed. " if allow_search
        else "Use only the supplied papers; do not search for other papers. ")
    instruction += answer_language_instruction(question) + "\n\nUser request:\n" + question
    return DispatchManifest(dispatch_id=dispatch_id, task=AgentTask(task_id=str(task_id), question=instruction,
        sources=[source.source_id for source in sources], allow_search=allow_search, max_papers=capacity,
        max_steps=min(settings.agent_max_steps, 32 + 8 * capacity),
        timeout_seconds=min(settings.agent_timeout_seconds, 300 + 60 * capacity),
        max_output_tokens=min(settings.agent_output_tokens, settings.agent_context_tokens - 2048)),
        sources=sources, runtime=RuntimeOptions(context_window=settings.agent_context_tokens, research=research,
            persist=settings.agent_transport == "tcloud" and settings.agent_persist))


def build_manifest(task_id: UUID, dispatch_id: UUID, task_type: str, question: str | None,
    papers: list[dict], settings: Settings) -> DispatchManifest:
    instructions = {
        "summary": "Summarize the selected paper: research problem, method, main findings and limitations. Cite original evidence.",
        "qa": "Answer the user question using only the selected paper and cite original evidence.",
        "review": "Compare the selected papers with a literature synthesis and a Markdown comparison table. Cite original evidence.",
    }
    instruction = instructions[task_type]
    instruction += " " + answer_language_instruction(question)
    if question:
        instruction += "\n\nUser request:\n" + question
    sources = _source_files(papers)
    count = len(sources)
    steps = min(settings.agent_max_steps, 32 + 8 * count)
    timeout = min(settings.agent_timeout_seconds, 300 + 60 * count)
    output = min(settings.agent_output_tokens, settings.agent_context_tokens - 2048)
    return DispatchManifest(dispatch_id=dispatch_id, task=AgentTask(task_id=str(task_id),
        question=instruction, sources=[source.source_id for source in sources], allow_search=False,
        max_papers=count, max_steps=steps, timeout_seconds=timeout, max_output_tokens=output),
        sources=sources, runtime=RuntimeOptions(context_window=settings.agent_context_tokens))
