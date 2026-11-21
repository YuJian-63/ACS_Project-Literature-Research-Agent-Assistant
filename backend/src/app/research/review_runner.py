import json
from datetime import datetime, timezone

from app.research.model_client import ModelProviderError
from app.research.review_protocol import (
    analysis_messages, assemble_review, section_analyses, synthesis_messages, token_estimate,
    validate_analysis, validate_section,
)
from app.research.review_store import ReviewLimitError, ReviewOwnershipLost
from app.research.validation import invalid_result_diagnostic


class ReviewResultError(ValueError):
    def __init__(self, message: str, details: dict):
        super().__init__(message)
        self.details = details


def run_staged_review(job, model, store, *, stopped=lambda: False, supplement=None):
    plan = job.review_plan

    def unit(key, make_messages, validate, output_cap, stage, progress):
        state = store.read()
        saved = state.get("units", {}).get(key, {})
        if "result" in saved:
            return saved["result"]
        attempts = saved.get("attempts", [])
        last_diagnostic = attempts[-1].get("diagnostic") if attempts else None
        compact = bool(attempts)
        for unused in range(len(attempts), 2):
            if stopped():
                raise ReviewOwnershipLost("Worker is stopping")
            elapsed = (datetime.now(timezone.utc) - job.started_at).total_seconds()
            remaining = job.timeout_seconds - elapsed
            if remaining <= 0:
                raise ReviewOwnershipLost("Review deadline elapsed")
            prompt = make_messages(compact, (last_diagnostic or {}).get("validation_reason"))
            estimated = token_estimate(prompt)
            if estimated + output_cap > plan["context_tokens"]:
                raise ReviewLimitError("Review unit exceeds model context")
            identity = store.reserve(key, estimated, output_cap, stage, "正在分析论文" if stage == "analyzing" else "正在生成综述章节", progress)
            completion = None
            result = None
            try:
                completion = model.complete(prompt, model_id=job.model_id, max_tokens=output_cap,
                                            timeout_seconds=min(plan["call_timeout_seconds"], remaining))
                if completion.finish_reason == "length":
                    raise ValueError("Model output reached its length limit")
                if completion.finish_reason not in {None, "stop"}:
                    raise ValueError("Model response did not finish normally")
                result = validate(completion.content)
                last_diagnostic = None
            except ModelProviderError:
                last_diagnostic = {"validation_reason": "model_request_failed", "model_finish_reason": None, "unit": key}
            except (ValueError, TypeError, KeyError) as error:
                message, last_diagnostic = invalid_result_diagnostic(error, finish_reason=completion.finish_reason if completion else None)
                last_diagnostic["unit"] = key
            store.settle(key, identity, completion, last_diagnostic, result=result)
            if result is not None:
                return result
            compact = True
        reason = last_diagnostic or {"validation_reason": "interrupted_attempt", "unit": key}
        if reason.get("validation_reason") == "model_request_failed":
            raise ModelProviderError("Review unit failed after its bounded retry")
        raise ReviewResultError("综述阶段在有限重试后仍未通过校验", reason)

    analyses = []
    for index, paper in enumerate(job.selected_papers, start=1):
        active = plan.get("active_ids", {}).get(paper["paper_id"])
        entries = [entry for entry in plan["registry"] if entry["paper_id"] == paper["paper_id"] and (active is None or entry["evidence_id"] in active)]
        key = "paper:" + paper["paper_id"]
        if not entries:
            empty = {"cells": {column["key"]: {"value": None, "evidence_ids": []} for column in plan["columns"]}}
            store.skip(key, empty)
            analyses.append(empty)
            continue
        analysis = unit(key,
            lambda compact, feedback: analysis_messages(paper, entries, job.question, plan, compact=compact, feedback=feedback),
            lambda raw: validate_analysis(raw, paper, plan), plan["analysis_output_tokens"], "analyzing",
            {"current": index, "total": len(job.selected_papers), "paper_id": paper["paper_id"]})
        if supplement is not None and any(cell["value"] is None for cell in analysis["cells"].values()):
            job, changed = supplement(job, analysis, paper, store)
            plan = job.review_plan
            if changed:
                active = plan.get("active_ids", {}).get(paper["paper_id"])
                entries = [entry for entry in plan["registry"] if entry["paper_id"] == paper["paper_id"] and entry["evidence_id"] in active]
                candidate = unit("paper-supplement:" + paper["paper_id"],
                    lambda compact, feedback: analysis_messages(paper, entries, job.question, plan, compact=compact, feedback=feedback),
                    lambda raw: validate_analysis(raw, paper, plan), plan["analysis_output_tokens"], "analyzing",
                    {"current": index, "total": len(job.selected_papers), "paper_id": paper["paper_id"]})
                analysis = {"cells": {key: cell if cell["value"] is not None else candidate["cells"][key]
                    for key, cell in analysis["cells"].items()}}
        analyses.append(analysis)
    sections = []
    if any(cell["evidence_ids"] for analysis in analyses for cell in analysis["cells"].values()):
        for index, section in enumerate(plan["sections"], start=1):
            if not any(cell["evidence_ids"] for analysis in section_analyses(section, analyses) for cell in analysis["cells"].values()):
                empty = {"paragraphs": [{"content_markdown": section["label"] + ": 证据不足 / Insufficient evidence", "evidence_ids": []}]}
                store.skip("section:" + section["key"], empty)
                sections.append(empty)
                continue
            sections.append(unit("section:" + section["key"],
                lambda compact, feedback: synthesis_messages(section, analyses, job.selected_papers, job.question, plan, compact=compact, feedback=feedback),
                lambda raw: validate_section(raw, analyses, plan, section), plan["section_output_tokens"], "synthesizing",
                {"current": index, "total": len(plan["sections"])}))
    else:
        sections = [{"paragraphs": [{"content_markdown": "证据不足 / Insufficient evidence", "evidence_ids": []}]}]
    if supplement is not None:
        missing = [{"paper_id": paper["paper_id"], "columns": [key for key, cell in analysis["cells"].items() if cell["value"] is None]}
            for paper, analysis in zip(job.selected_papers, analyses, strict=True)]
        status = "no_parsed_text" if not job.source_evidence else "partial" if any(item["columns"] for item in missing) else "answered"
        store.save_search("outcome", {"status": status, "papers": missing},
            message="已完成证据检查", payload={"evidence_status": status})
    return assemble_review(analyses, sections, job.selected_papers, job.evidence, plan, source_evidence=getattr(job, "source_evidence", None))
