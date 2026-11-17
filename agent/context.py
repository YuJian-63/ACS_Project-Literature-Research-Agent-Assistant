"""Prepare model input without changing the stored conversation.

Counts are estimates, calibrated against provider input usage when the request
prefix and tool definitions match. They do not replace a service tokenizer.
"""

import json
import math
from dataclasses import dataclass, field

from langchain_core.messages import BaseMessage, convert_to_openai_messages


def _request_parts(messages: list[BaseMessage], tools: list[dict]) -> tuple[list[str], str]:
    # Count model-visible fields, excluding local IDs and response/usage metadata.
    parts = [
        json.dumps(message, ensure_ascii=False, sort_keys=True)
        for message in convert_to_openai_messages(messages)
    ]
    return parts, json.dumps(tools, ensure_ascii=False, sort_keys=True) if tools else ""


def _estimate(text: str) -> int:
    ascii_chars = sum(character.isascii() for character in text)
    return math.ceil(ascii_chars / 3 + (len(text) - ascii_chars) * 2)


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


def prepare_context(
    messages: list[BaseMessage],
    *,
    tools: list[dict],
    context_window: int | None,
    max_output_tokens: int,
    counter: TokenCounter,
) -> PreparedContext:
    """Baseline policy: keep every message and estimate this request's input.

    The caller enforces input + output <= window. Future policies may use the
    supplied limits to prepare a smaller view; stored history stays separate.
    """
    tokens, method = counter.estimate(messages, tools)
    return PreparedContext(messages, tokens, method)
