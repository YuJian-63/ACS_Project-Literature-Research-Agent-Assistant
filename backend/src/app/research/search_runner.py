import json
import re
from dataclasses import replace
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.research.document_search import (
    expansion_messages, local_query_plan, retrieval_diagnostic, select_document_evidence, validate_query_plan,
)
from app.research.model_client import ModelProviderError
from app.research.retrieval import EvidenceChunk, build_citation_passages
from app.research.review_protocol import token_estimate
from app.research.review_runner import ReviewResultError
from app.research.review_store import ReviewLimitError, ReviewOwnershipLost
from app.research.search_policy import answer_messages
from app.research.validation import ValidatedResult, invalid_result_diagnostic, validate_paragraph_result, validate_selected_evidence_result


class SearchAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["answered", "partial", "needs_more_evidence"] = "answered"
    missing_aspects: list[str] = Field(default_factory=list, max_length=3)
    paragraphs: list[dict] = Field(default_factory=list, max_length=100)


def remaining_seconds(job) -> float:
    return job.timeout_seconds - (datetime.now(timezone.utc) - job.started_at).total_seconds()


def checked_call(job, model, store, key, messages, output_cap, validate, *, stage="generating", stopped=lambda: False):
    saved = store.read().get("units", {}).get(key, {})
    if "result" in saved:
        return saved["result"]
    diagnostic = None
    for unused in range(len(saved.get("attempts", [])), 2):
        if stopped() or remaining_seconds(job) <= 0:
            raise ReviewOwnershipLost("Research execution interrupted")
        input_cap = token_estimate(messages)
        if input_cap + output_cap > job.search_policy["context_tokens"]:
            raise ReviewLimitError("Research call exceeds context limit")
        identity = store.reserve(key, input_cap, output_cap, stage, "正在生成研究结果", {})
        completion, result = None, None
        try:
            completion = model.complete(messages, model_id=job.model_id, max_tokens=output_cap,
                timeout_seconds=min(job.model_timeout_seconds, remaining_seconds(job)))
            if completion.finish_reason not in {None, "stop"}:
                raise ValueError("Model response did not finish normally")
            result = validate(completion.content)
            diagnostic = None
        except ModelProviderError:
            diagnostic = {"validation_reason": "model_request_failed", "unit": key}
        except (ValueError, KeyError, TypeError) as error:
            unused_message, diagnostic = invalid_result_diagnostic(error, finish_reason=completion.finish_reason if completion else None)
        store.settle(key, identity, completion, diagnostic, result=result)
        if result is not None:
            return result
    if diagnostic and diagnostic.get("validation_reason") == "model_request_failed":
        raise ModelProviderError("Research model call failed after its bounded retry")
    raise ReviewResultError("模型结果未通过证据校验", diagnostic or {"validation_reason": "interrupted_attempt"})


def prepare_search(job, model, store, *, stopped=lambda: False):
    state = store.read()
    saved_query = state.get("search", {}).get("query")
    if saved_query is None:
        query = job.search_policy["local_query"]
        degraded = None
        if job.search_policy["expand"]:
            attempt = state.get("units", {}).get("search:expand", {})
            if "result" in attempt:
                query = attempt["result"]
            elif attempt.get("attempts"):
                degraded = "interrupted_expansion"
            else:
                if stopped() or remaining_seconds(job) <= 0:
                    raise ReviewOwnershipLost("Research execution interrupted")
                messages = expansion_messages(job.question, job.selected_papers)
                identity = store.reserve("search:expand", token_estimate(messages), 512, "retrieving", "正在扩展跨语言检索词", {})
                completion, expanded, diagnostic = None, None, None
                try:
                    completion = model.complete(messages, model_id=job.model_id, max_tokens=512,
                        timeout_seconds=min(15, remaining_seconds(job)))
                    if completion.finish_reason not in {None, "stop"}:
                        raise ValueError("Incomplete query expansion")
                    expanded = validate_query_plan(completion.content, job.question)
                except ModelProviderError:
                    degraded = "expansion_unavailable"
                except (ValueError, KeyError, TypeError):
                    degraded = "invalid_expansion"
                if degraded:
                    diagnostic = {"validation_reason": degraded}
                store.settle("search:expand", identity, completion, diagnostic, result=expanded)
                if expanded is not None:
                    query = expanded
        store.save_search("query", {"plan": query, "degraded": degraded},
            message="检索词扩展不可用，已使用原问题和论文结构继续检索" if degraded else "检索计划已保存",
            payload={"retrieval_status": "degraded" if degraded else "planned", "reason": degraded}, warning=bool(degraded))
        saved_query = store.read()["search"]["query"]
    query = saved_query["plan"]
    checkpoints = store.read().get("search", {})
    selection = checkpoints.get("selection")
    if selection is None:
        if job.task_type == "review":
            evidence = [chunk for paper in job.selected_papers for chunk in select_document_evidence(
                [item for item in job.source_evidence if item.paper_id == paper["paper_id"]], "review", query,
                job.review_plan["evidence_chars_per_paper"], max_chunks=4)]
        else:
            evidence = select_document_evidence(job.source_evidence, job.task_type, query, job.evidence_context_chars)
        diagnostic = retrieval_diagnostic(job.source_evidence, evidence, query)
        selection = {"evidence": [chunk.model_dump() for chunk in evidence], "diagnostic": diagnostic}
        store.save_search("selection", selection, message="已选择论文证据", payload={"retrieval": diagnostic})
    evidence = [EvidenceChunk.model_validate(chunk) for chunk in selection["evidence"]]
    if job.task_type == "review":
        supplements = [value for key, value in checkpoints.items() if key.startswith("supplement:")]
        if supplements:
            selection = max([selection, *supplements], key=lambda value: len(value["evidence"]))
            evidence = [EvidenceChunk.model_validate(chunk) for chunk in selection["evidence"]]
        plan = {**job.review_plan, "registry": registry(evidence)}
        if "active_ids" in selection:
            plan["active_ids"] = selection["active_ids"]
        return replace(job, evidence=evidence, review_plan=plan)
    return replace(job, evidence=evidence)


def registry(evidence):
    papers = {chunk.chunk_id: chunk.paper_id for chunk in evidence}
    return [{**passage.model_dump(), "paper_id": papers[passage.chunk_id]}
        for passage in build_citation_passages(evidence)]


def _supplement_source(job, query, missing, allowance, max_chunks, previous, paper_id=None):
    source = [chunk for chunk in job.source_evidence if paper_id is None or chunk.paper_id == paper_id]
    translated = local_query_plan(" ".join(missing))
    expanded = {"intent": "specific", "question": " ".join(missing) if missing else query.get("question", ""),
        "queries": [*translated["queries"][1:], *missing][:3] if missing else query["queries"]}
    known = {(chunk.chunk_id, chunk.content) for chunk in previous}
    count = min(max_chunks, len(source))
    if not count:
        return []
    window_chars = max(1, min(1000, allowance // count))
    candidates = select_document_evidence(source, "qa", expanded, window_chars * len(source), max_chunks=len(source))
    fresh = [chunk for chunk in candidates if (chunk.chunk_id, chunk.content) not in known]
    return select_document_evidence(fresh, "qa", expanded, allowance, max_chunks=max_chunks)


def merge_supported_answers(first, first_job, second, second_job):
    paragraphs, seen = [], set()
    for answer, job in ((first, first_job), (second, second_job)):
        passages = {item.evidence_id: item for item in build_citation_passages(job.evidence)}
        for paragraph in answer["paragraphs"]:
            content = paragraph["content_markdown"]
            if not paragraph["evidence_ids"] or content in seen:
                continue
            seen.add(content)
            paragraphs.append({"content_markdown": content, "citations": [
                {"chunk_id": passages[identity].chunk_id, "quote": passages[identity].quote}
                for identity in paragraph["evidence_ids"]]})
    return validate_paragraph_result(json.dumps({"paragraphs": paragraphs[:100]}), first_job.source_evidence)


def supplement_review(job, analysis, paper, store):
    key = "supplement:" + paper["paper_id"]
    saved = store.read().get("search", {}).get(key)
    if saved is not None:
        return job, saved["changed"]
    query = store.read()["search"]["query"]["plan"]
    missing = [column["label"] for column in job.review_plan["columns"] if analysis["cells"][column["key"]]["value"] is None]
    current = [chunk for chunk in job.evidence if chunk.paper_id == paper["paper_id"]]
    fresh = _supplement_source(job, query, missing, max(1, job.review_plan["evidence_chars_per_paper"] // 2), 2, current, paper["paper_id"])
    combined = [*job.evidence, *fresh]
    entries = registry(combined)
    used = {identity for cell in analysis["cells"].values() for identity in cell["evidence_ids"]}
    old = [entry["evidence_id"] for entry in entries if entry["paper_id"] == paper["paper_id"] and entry["evidence_id"] in used][:2]
    if len(old) < 2:
        old += [entry["evidence_id"] for entry in entries[:len(job.evidence)] if entry["paper_id"] == paper["paper_id"] and entry["evidence_id"] not in old][:2 - len(old)]
    active = {**job.review_plan.get("active_ids", {}), paper["paper_id"]: [*old, *[entry["evidence_id"] for entry in entries[len(job.evidence):]]]}
    snapshot = {"evidence": [chunk.model_dump() for chunk in combined], "active_ids": active, "changed": bool(fresh)}
    store.save_search(key, snapshot, message="已补充检索论文证据", payload={"paper_id": paper["paper_id"], "new_chunks": len(fresh)})
    return replace(job, evidence=combined, review_plan={**job.review_plan, "registry": entries, "active_ids": active}), bool(fresh)


def validate_answer(raw, job):
    draft = SearchAnswer.model_validate_json(raw)
    if any(not item.strip() or len(item) > 160 for item in draft.missing_aspects):
        raise ValueError("Invalid missing aspect")
    if draft.status in {"answered", "partial"} and not draft.paragraphs:
        raise ValueError("Answer has no paragraphs")
    if draft.paragraphs:
        validate_selected_evidence_result(json.dumps({"paragraphs": draft.paragraphs}), job.evidence, source_evidence=job.source_evidence)
    if draft.status == "answered" and any(not paragraph["evidence_ids"] for paragraph in draft.paragraphs):
        raise ValueError("Answered paragraphs require supporting evidence")
    return draft.model_dump()


def insufficient_result(job, *, no_text=False):
    english = bool(re.search(r"\bEnglish\b|英文", job.question or "", re.I)) or not re.search(r"[\u3400-\u9fff]", job.question or "")
    message = ("No parsed text is available for analysis. Check the paper parsing result." if no_text else
        "The retrieved passages do not provide enough evidence to answer this question. This does not establish that the information is absent from the full paper.") if english else (
        "论文没有可用于分析的解析文本，请检查解析结果。" if no_text else
        "当前检索到的片段不足以支持回答本问题；这不代表论文全文中不存在相关信息。")
    return ValidatedResult(content_markdown=message, citations=[])


def run_single_search(job, model, store, *, stopped=lambda: False):
    if not job.evidence:
        store.save_search("outcome", {"status": "no_parsed_text"}, message="论文没有可用于分析的解析文本")
        return insufficient_result(job, no_text=True)
    first = checked_call(job, model, store, "answer:0", answer_messages(job.task_type, job.question, job.evidence),
        job.max_output_tokens, lambda raw: validate_answer(raw, job), stopped=stopped)
    chosen, chosen_job, merged = first, job, None
    can_supplement = job.task_type == "qa" or job.search_policy.get("supplement_rounds", 0) > 0
    if can_supplement and first["status"] != "answered":
        saved = store.read().get("search", {}).get("answer_selection")
        if saved is None:
            query = store.read()["search"]["query"]["plan"]
            fresh = _supplement_source(job, query, first["missing_aspects"], job.evidence_context_chars, 16, job.evidence)
            saved = {"evidence": [chunk.model_dump() for chunk in fresh]}
            store.save_search("answer_selection", saved, message="已补充检索论文证据", payload={"new_chunks": len(fresh)})
        if saved["evidence"]:
            second_job = replace(job, evidence=[EvidenceChunk.model_validate(chunk) for chunk in saved["evidence"]])
            try:
                second = checked_call(second_job, model, store, "answer:1", answer_messages(job.task_type, job.question, second_job.evidence),
                    job.max_output_tokens, lambda raw: validate_answer(raw, second_job), stopped=stopped)
            except (ModelProviderError, ReviewResultError, ReviewLimitError):
                second = {"status": "needs_more_evidence", "paragraphs": [], "missing_aspects": first["missing_aspects"]}
            first_supported = sum(bool(paragraph["evidence_ids"]) for paragraph in first["paragraphs"])
            second_supported = sum(bool(paragraph["evidence_ids"]) for paragraph in second["paragraphs"])
            if second["status"] == "answered" or second_supported > 0:
                chosen, chosen_job = second, second_job
                if second["status"] != "answered" and first_supported:
                    merged = merge_supported_answers(first, job, second, second_job)
    status = "insufficient_selected_evidence" if chosen["status"] == "needs_more_evidence" else chosen["status"]
    store.save_search("outcome", {"status": status, "missing_aspects": chosen["missing_aspects"]},
        message="已完成证据检查", payload={"evidence_status": status, "missing_aspects": chosen["missing_aspects"]})
    if not chosen["paragraphs"]:
        return insufficient_result(job)
    if merged is not None:
        return merged
    return validate_selected_evidence_result(json.dumps({"paragraphs": chosen["paragraphs"]}), chosen_job.evidence, source_evidence=job.source_evidence)
