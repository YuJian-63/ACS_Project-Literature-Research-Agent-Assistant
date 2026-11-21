import json
import math

from app.research.retrieval import EvidenceChunk, build_citation_passages
from app.research.review_protocol import analysis_messages, synthesis_messages, token_estimate
from app.tasks.language import uses_english_labels

POLICY_VERSION = "review-auto-v1"
WORKFLOW_VERSION = "langgraph-review-v2"
PROMPT_VERSION = "evidence-review-v3"


def sample_evidence(groups: dict[str, list[EvidenceChunk]], per_paper_chars: int) -> list[EvidenceChunk]:
    selected = []
    for paper_id, chunks in groups.items():
        ordered = sorted(chunks, key=lambda chunk: (chunk.chunk_index, chunk.chunk_id))
        if any(chunk.paper_id != paper_id for chunk in ordered):
            raise ValueError("Evidence belongs to another paper")
        count = min(4, len(ordered))
        if not count:
            continue
        positions = [round(index * (len(ordered) - 1) / (count - 1)) for index in range(count)] if count > 1 else [0]
        allowance = min(1000, per_paper_chars // count)
        for position in positions:
            chunk = ordered[position]
            selected.append(chunk.model_copy(update={"content": chunk.content[:allowance]}))
    return selected


def build_review_plan(papers: list[dict], groups: dict[str, list[EvidenceChunk]], question: str, settings, *, search: dict | None = None, expansion_reserve: int = 0) -> tuple[dict, list[EvidenceChunk]]:
    if not 2 <= len(papers) <= 20 or len({paper["paper_id"] for paper in papers}) != len(papers):
        raise ValueError("Review requires 2-20 distinct papers")
    if set(groups) != {paper["paper_id"] for paper in papers}:
        raise ValueError("Evidence groups do not match papers")
    english = uses_english_labels(question)
    columns = [{"key": key, "label": label} for key, label in zip(
        ("objective", "method", "evaluation", "limitations"),
        ("Research objective", "Agent method", "Evaluation", "Limitations") if english else ("研究目标", "代理方法", "评估方式", "局限"), strict=True)]
    sections = [{"key": key, "label": label} for key, label in zip(
        ("overview", "comparison", "limitations"),
        ("Research scope and common ground", "Methods and evaluation differences", "Limitations and comparability") if english else ("研究目标与共同点", "方法和评估差异", "局限与可比性"), strict=True)]
    sizes = [(200, 400, settings.review_evidence_chars), (120, 300, min(2400, settings.review_evidence_chars)), (80, 240, min(1600, settings.review_evidence_chars)), (60, 200, min(1000, settings.review_evidence_chars)), (40, 160, min(1000, settings.review_evidence_chars)), (30, 120, min(1000, settings.review_evidence_chars))]
    if search is not None:
        sizes.extend([(20, 100, min(800, settings.review_evidence_chars)), (16, 80, min(600, settings.review_evidence_chars))])
    for cell_chars, paragraph_chars, evidence_chars in sizes:
        if search is None:
            evidence = sample_evidence(groups, evidence_chars)
        else:
            from app.research.document_search import excerpt_byte_bound, select_document_evidence
            evidence = [chunk for source in groups.values() for chunk in select_document_evidence(
                source, "review", search, evidence_chars, max_chunks=4)]
        by_chunk = {chunk.chunk_id: chunk for chunk in evidence}
        registry = [{**passage.model_dump(), "paper_id": by_chunk[passage.chunk_id].paper_id} for passage in build_citation_passages(evidence)]
        plan = {"version": POLICY_VERSION, "columns": columns, "sections": sections, "cell_chars": cell_chars,
                "paragraph_chars": paragraph_chars, "evidence_chars_per_paper": evidence_chars,
                "context_tokens": settings.review_context_tokens, "registry": registry, "retry_reserve": 2 if len(papers) <= 12 else 1}
        analysis_inputs, analysis_outputs, examples, planning_registry = [], [], [], []
        for paper in papers:
            entries = [entry for entry in registry if entry["paper_id"] == paper["paper_id"]]
            if search is not None and entries:
                byte_bound = excerpt_byte_bound(groups[paper["paper_id"]], max(1, min(1000, evidence_chars // 4)))
                worst_quote = "\x01" * (byte_bound // 6) + "x" * (byte_bound % 6)
                slots = min(6, 2 * len(groups[paper["paper_id"]]))
                entries = [{**entries[0], "quote": worst_quote, "evidence_id": f"E{len(planning_registry) + index + 10000}"} for index in range(slots)]
            planning_registry.extend(entries)
            ids = [entry["evidence_id"] for entry in sorted(entries, key=lambda entry: len(json.dumps(entry["quote"], ensure_ascii=False).encode("utf-8")), reverse=True)]
            example = {"cells": {column["key"]: {"value": "测" * cell_chars if ids else None,
                       "evidence_ids": [ids[(index * 2 + offset) % len(ids)] for offset in range(min(2, len(ids)))] if ids else []}
                       for index, column in enumerate(columns)}}
            examples.append(example)
            actual_input = token_estimate(analysis_messages(paper, entries, question, plan, feedback="x" * 128))
            if search is not None:
                actual_input = max(actual_input, token_estimate(analysis_messages(paper, entries, question, plan, feedback="x" * 128)))
            analysis_inputs.append(actual_input)
            analysis_outputs.append(max(768, token_estimate([{"content": json.dumps(example, ensure_ascii=False)}]) + 128))
        plan["analysis_output_tokens"] = max(analysis_outputs)
        estimate_plan = {**plan, "registry": planning_registry} if search is not None else plan
        section_inputs = [token_estimate(synthesis_messages(section, examples, papers, question, estimate_plan, feedback="x" * 128)) for section in sections]
        plan["section_output_tokens"] = max(1024, math.ceil(paragraph_chars * 6 + 700))
        reserves = [size + plan["analysis_output_tokens"] for size in analysis_inputs] + [size + plan["section_output_tokens"] for size in section_inputs]
        supplements = len(papers) if search is not None else 0
        extra = supplements * max(size + plan["analysis_output_tokens"] for size in analysis_inputs) + expansion_reserve
        total = sum(reserves) + plan["retry_reserve"] * max(reserves) + extra + 512
        if max(plan["analysis_output_tokens"], plan["section_output_tokens"]) > settings.review_output_tokens:
            continue
        if max(reserves) > settings.review_context_tokens or total > settings.review_task_tokens:
            continue
        calls = len(papers) + len(sections) + plan["retry_reserve"] + supplements + bool(expansion_reserve)
        call_timeout = min(settings.review_call_timeout_seconds, (settings.review_timeout_seconds - 30) / calls)
        if call_timeout < 5:
            continue
        plan.update(max_tokens=total, max_steps=calls, timeout_seconds=math.ceil(calls * call_timeout + 30), call_timeout_seconds=call_timeout)
        if search is not None:
            plan["analysis_input_cap"] = max(analysis_inputs)
        return plan, evidence
    raise ValueError("The review cannot fit the configured server limits")
