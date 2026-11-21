import math

from app.research.retrieval import EvidenceChunk, build_messages, select_evidence

POLICY_VERSION = "single-auto-v1"
PROMPT_VERSION = "evidence-v4"


def automatic_budget(task) -> bool:
    return task.workflow_version == "langgraph-review-v2" or task.run_config.get("budget_mode") == "automatic"


def build_task_plan(task_type: str, question: str | None, chunks: list[EvidenceChunk], settings) -> tuple[dict, list[EvidenceChunk]]:
    if task_type not in {"summary", "qa"}:
        raise ValueError("Single-paper task required")
    char_limit = settings.evidence_context_chars
    for _ in range(20):
        bounded = [chunk.model_copy(update={"content": chunk.content[:char_limit]}) for chunk in chunks]
        evidence = select_evidence(bounded, task_type, question, char_limit)
        messages = build_messages(task_type, question, evidence, prompt_version=PROMPT_VERSION) if evidence else []
        input_tokens = sum(len(message["content"].encode("utf-8")) for message in messages) + 512 if evidence else 0
        evidence_chars = sum(len(chunk.content) for chunk in evidence)
        desired_output = (2048 + math.ceil(evidence_chars / 8)) if task_type == "summary" else (1536 + math.ceil(evidence_chars / 12) + 2 * len(question or ""))
        output_tokens = min(settings.research_output_tokens, math.ceil(desired_output / 256) * 256)
        total_tokens = input_tokens + output_tokens + 512
        if input_tokens + output_tokens <= settings.research_context_tokens and total_tokens <= settings.research_task_tokens:
            call_timeout = min(settings.research_call_timeout_seconds, math.ceil(15 + input_tokens / 200 + output_tokens / 30))
            return {"version": POLICY_VERSION, "estimated_input_tokens": input_tokens,
                    "max_output_tokens": output_tokens, "max_tokens": total_tokens, "max_steps": 1,
                    "model_timeout_seconds": call_timeout, "timeout_seconds": math.ceil(call_timeout + 30),
                    "evidence_context_chars": char_limit}, evidence
        if char_limit == 1:
            break
        char_limit = max(1, char_limit // 2)
    raise ValueError("The task cannot fit the configured server limits")
