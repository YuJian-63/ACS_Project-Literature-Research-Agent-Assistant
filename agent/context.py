"""Prepare model input without changing the stored conversation.

Counts are estimates, calibrated against provider input usage when the request
prefix and tool definitions match. They do not replace a service tokenizer.
"""

import json
import math
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    ToolCall,
    ToolMessage,
    convert_to_openai_messages,
)

DEFAULT_FINALIZE_RATIO = 0.9
_PAPER_TOOLS = {"open_paper", "read_paper", "retrieve", "summarize_paper", "search_papers"}


def _request_parts(messages: list[BaseMessage], tools: list[dict]) -> tuple[list[str], str]:
    # Count model-visible fields, excluding local IDs and response/usage metadata.
    parts = [
        json.dumps(message, ensure_ascii=False, sort_keys=True)
        for message in convert_to_openai_messages(messages)
    ]
    return parts, json.dumps(tools, ensure_ascii=False, sort_keys=True) if tools else ""


def _estimate(text: str) -> int:
    ascii_chars = sum(character.isascii() for character in text)
    return math.ceil(ascii_chars / 4 + (len(text) - ascii_chars) * 2)


@dataclass
class TokenCounter:
    """One request stream's last usable API input count and immutable prefix."""

    messages: list[str] = field(default_factory=list)
    tools: str = ""
    input_tokens: int | None = None

    def estimate(self, messages: list[BaseMessage], tools: list[dict]) -> tuple[int, str]:
        parts, tool_text = _request_parts(messages, tools)
        if (
            self.input_tokens is not None
            and tool_text == self.tools
            and parts[: len(self.messages)] == self.messages
        ):
            added = sum(_estimate(part) + 8 for part in parts[len(self.messages) :])
            return self.input_tokens + added, "usage_anchored_estimate"
        tokens = 3 + _estimate(tool_text) + sum(_estimate(part) + 8 for part in parts)
        return tokens, "heuristic"

    def observe(
        self, messages: list[BaseMessage], tools: list[dict], input_tokens: int | None
    ) -> None:
        if type(input_tokens) is int and input_tokens >= 0:
            self.messages, self.tools = _request_parts(messages, tools)
            self.input_tokens = input_tokens


@dataclass
class PreparedContext:
    messages: list[BaseMessage]
    input_tokens_estimate: int
    count_method: str
    compaction: dict | None = None


def prepare_context(
    messages: list[BaseMessage],
    *,
    tools: list[dict],
    context_window: int | None,
    max_output_tokens: int,
    counter: TokenCounter,
) -> PreparedContext:
    """Baseline policy: keep every message and estimate this request's input.

    The caller enforces input + output <= window.
    """
    tokens, method = counter.estimate(messages, tools)
    return PreparedContext(messages, tokens, method)


def _tool_observations(messages: list[BaseMessage]) -> tuple[int, list[tuple[int, ToolCall, dict]]]:
    """Decode known observations only from completely answered tool-call batches."""
    through = 0
    observations = []
    for start, request in enumerate(messages):
        if not isinstance(request, AIMessage) or not request.tool_calls:
            continue
        calls = {call["id"]: call for call in request.tool_calls}
        end = start + 1 + len(request.tool_calls)
        replies = messages[start + 1 : end]
        if (
            len(calls) != len(request.tool_calls)
            or len(replies) != len(calls)
            or not all(isinstance(reply, ToolMessage) for reply in replies)
            or {reply.tool_call_id for reply in replies} != calls.keys()
            or (end < len(messages) and isinstance(messages[end], ToolMessage))
        ):
            continue
        through = end
        for index, reply in enumerate(replies, start + 1):
            call = calls[reply.tool_call_id]
            if call["name"] not in _PAPER_TOOLS or not isinstance(reply.content, str):
                continue
            try:
                data = json.loads(reply.content)
            except ValueError:
                continue
            if isinstance(data, dict) and "error" not in data:
                observations.append((index, call, data))
    return through, observations


def prepare_final_context(
    prepared: PreparedContext, instruction: BaseMessage, window: int, max_output_tokens: int
) -> PreparedContext:
    """Fit one tool-free answer using only the already prepared conversation."""
    counter = TokenCounter()
    messages = prepared.messages
    view = [*messages, instruction]
    budget = window - max_output_tokens
    tokens = prepared.input_tokens_estimate + counter.estimate([instruction], [])[0]
    if tokens <= budget:
        return PreparedContext(view, tokens, "finalize_conservative_estimate")

    tokens, method = counter.estimate(view, [])
    if tokens <= budget:
        return PreparedContext(view, tokens, method)

    # Keep the original instructions and question. Replace tool conversations
    # with complete, citeable evidence from the prepared view, newest batch first.
    view = [message for message in messages if message.type in {"system", "human"}]
    base_tokens, _ = counter.estimate([*view, instruction], [])
    remaining = budget - base_tokens
    _, observations = _tool_observations(messages)
    pairs = []
    for index, call, data in reversed(observations):
        if call["name"] not in {"read_paper", "retrieve", "summarize_paper"}:
            continue
        field = "summaries" if call["name"] == "summarize_paper" else "chunks"
        items = data.get(field)
        if not isinstance(items, list):
            continue
        request = AIMessage(content="", tool_calls=[call])
        selected = []
        pair = None
        for item in items:
            if not isinstance(item, dict) or not (item.get("source_text") or item.get("summary")):
                continue
            content = json.dumps({field: [*selected, item]}, ensure_ascii=False)
            reply = messages[index].model_copy(update={"content": content})
            cost, _ = counter.estimate([request, reply], [])
            if cost <= remaining:
                selected.append(item)
                pair = (request, reply, cost)
        if pair:
            pairs.append(pair)
            remaining -= pair[2]
    for request, reply, _ in reversed(pairs):
        view.extend([request, reply])
    view.append(instruction)
    tokens, method = counter.estimate(view, [])
    return PreparedContext(view, tokens, method)


def _compact_observations(observations: list[tuple[int, ToolCall, dict]]) -> tuple[dict, dict]:
    selected = set()
    for _, call, data in observations:
        if call["name"] == "search_papers":
            continue
        sources = data.get("source_ids", [data.get("source_id")])
        if isinstance(sources, list):
            for source in sources:
                if isinstance(source, str):
                    source = source.removeprefix("arxiv:")
                    selected.add(source)
                    selected.add(re.sub(r"(?:v\d+|@[0-9a-f]{12})$", "", source))

    replacements = {}
    counts = {"duplicate_chunks": 0, "shortened_receipts": 0, "removed_snippets": 0}
    originals = set()
    visible_ids = set()
    for index, call, data in observations:
        name = call["name"]
        changed = False
        chunks = data.get("chunks")
        if name in {"read_paper", "retrieve"} and isinstance(chunks, list):
            for chunk in chunks:
                if not isinstance(chunk, dict):
                    continue
                source = chunk.get("source_id", data.get("source_id"))
                key = (source, chunk.get("chunk_id"), chunk.get("source_text"))
                if not all(isinstance(value, str) and value for value in key):
                    continue
                if key in originals:
                    del chunk["source_text"]
                    chunk["see_earlier"] = True
                    counts["duplicate_chunks"] += 1
                    changed = True
                else:
                    originals.add(key)
                    visible_ids.add(chunk["chunk_id"])

        if name == "summarize_paper" and isinstance(data.get("summaries"), list):
            for summary in data["summaries"]:
                if isinstance(summary, dict) and isinstance(summary.get("chunk_ids"), list):
                    visible_ids.update(key for key in summary["chunk_ids"] if isinstance(key, str))

        if (name == "read_paper" and data.get("status") == "already_read" and chunks == []) or (
            name == "summarize_paper"
            and data.get("status") == "already_summarized"
            and data.get("summaries") == []
        ):
            field_name = (
                "previously_read_chunk_ids"
                if name == "read_paper"
                else "previously_summarized_chunk_ids"
            )
            ids = data.get(field_name)
            if (
                isinstance(ids, list)
                and ids
                and all(isinstance(key, str) and key in visible_ids for key in ids)
            ):
                del data[field_name]
                data["earlier_chunk_count"] = len(ids)
                counts["shortened_receipts"] += 1
                changed = True

        if name == "search_papers" and isinstance(data.get("results"), list):
            for hit in data["results"]:
                if not isinstance(hit, dict) or not isinstance(hit.get("source"), str):
                    continue
                if hit["source"].removeprefix("arxiv:") in selected and hit.get("snippet"):
                    del hit["snippet"]
                    counts["removed_snippets"] += 1
                    changed = True
        if changed:
            replacements[index] = json.dumps(data, ensure_ascii=False)
    return replacements, counts


@dataclass
class CompactHistory:
    """Pressure-triggered projection of one run's append-only canonical messages."""

    trigger_ratio: float = DEFAULT_FINALIZE_RATIO
    _replacements: dict[int, str] = field(default_factory=dict, init=False, repr=False)
    _last_attempt: int = field(default=-1, init=False, repr=False)

    def __post_init__(self):
        if type(self.trigger_ratio) not in (int, float) or not 0 < self.trigger_ratio <= 1:
            raise ValueError("trigger_ratio must be in (0, 1]")

    def __call__(
        self,
        messages: list[BaseMessage],
        *,
        tools: list[dict],
        context_window: int | None,
        max_output_tokens: int,
        counter: TokenCounter,
    ) -> PreparedContext:
        view = list(messages)
        for index, content in self._replacements.items():
            view[index] = messages[index].model_copy(update={"content": content})
        before, method = counter.estimate(view, tools)
        prepared = PreparedContext(view, before, method)
        if (
            context_window is None
            or len(view) <= self._last_attempt
            or before + max_output_tokens < context_window * self.trigger_ratio
        ):
            return prepared

        started = time.monotonic()
        through, observations = _tool_observations(view)
        if through <= self._last_attempt:
            return prepared
        self._last_attempt = through
        replacements, counts = _compact_observations(observations)
        after, after_method, saved = before, method, 0
        outcome = "no_gain"
        if replacements:
            candidate = list(view)
            for index, content in replacements.items():
                candidate[index] = view[index].model_copy(update={"content": content})
            after, after_method = counter.estimate(candidate, tools)
            # Editing an already-sent prefix invalidates its usage anchor. Measure
            # text reduction on the same scale; admit the request using its own estimate.
            heuristic = TokenCounter()
            original_size = before if method == "heuristic" else heuristic.estimate(view, tools)[0]
            new_size = (
                after if after_method == "heuristic" else heuristic.estimate(candidate, tools)[0]
            )
            saved = original_size - new_size
            if saved > 0 and after < before:
                self._replacements.update(replacements)
                prepared = PreparedContext(candidate, after, after_method)
                outcome = "applied"
        prepared.compaction = {
            "outcome": outcome,
            "before_tokens": before,
            "after_tokens": after,
            "before_method": method,
            "after_method": after_method,
            "heuristic_tokens_saved": saved,
            "through_message": through,
            "elapsed_seconds": round(time.monotonic() - started, 6),
            **counts,
        }
        return prepared


def resolve_context_policy(policy: str | Callable, finalize_ratio: float | None) -> Callable:
    if isinstance(policy, CompactHistory):
        return CompactHistory(policy.trigger_ratio)
    if callable(policy):
        return policy
    if policy == "full":
        return prepare_context
    if policy == "compact":
        return CompactHistory(finalize_ratio if finalize_ratio is not None else 1.0)
    raise ValueError("context_policy must be 'full', 'compact' or a callable")
