import json
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app.research.model_client import ChatModel
from app.research.retrieval import EvidenceChunk, build_messages


class ResearchState(TypedDict, total=False):
    task_type: str
    question: str | None
    evidence: list[EvidenceChunk]
    selected_papers: list[dict[str, str]]
    model_id: str
    prompt_version: str | None
    max_tokens: int
    timeout_seconds: float
    output: str
    input_tokens: int | None
    output_tokens: int | None
    model_calls: int
    finish_reason: str | None


def build_research_graph(model: ChatModel):
    def generate(state: ResearchState) -> dict:
        evidence = state["evidence"]
        if not evidence:
            payload = {
                "content_markdown": "## 证据不足\n\n在已解析论文中未检索到可直接支持本问题的证据。请调整问题或检查论文内容。",
                "citations": [],
            }
            if state["task_type"] != "review":
                version = state.get("prompt_version") or "evidence-v4"
                if version == "evidence-v4":
                    payload = {"paragraphs": [{"content_markdown": payload["content_markdown"], "evidence_ids": []}]}
                elif version == "evidence-v3":
                    payload = {"paragraphs": [payload]}
            return {"output": json.dumps(payload, ensure_ascii=False), "input_tokens": 0, "output_tokens": 0, "model_calls": 0}
        completion = model.complete(
            build_messages(state["task_type"], state.get("question"), evidence,
                           selected_papers=state.get("selected_papers"), prompt_version=state.get("prompt_version")),
            model_id=state["model_id"],
            max_tokens=state["max_tokens"],
            timeout_seconds=state.get("timeout_seconds", 60),
        )
        return {
            "output": completion.content,
            "input_tokens": completion.input_tokens,
            "output_tokens": completion.output_tokens,
            "model_calls": 1,
            "finish_reason": getattr(completion, "finish_reason", None),
        }

    graph = StateGraph(ResearchState)
    graph.add_node("generate", generate)
    graph.add_edge(START, "generate")
    graph.add_edge("generate", END)
    return graph.compile()
