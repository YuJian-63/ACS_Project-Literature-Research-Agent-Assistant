"""Qwen chat adapter and a real tool-call round trip: python -m apis.model."""

import argparse
import json
import os
import time

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from openai import OpenAIError

from config import load_env, require_env


def make_model(*, max_tokens: int = 2048, timeout: float = 60) -> ChatOpenAI:
    load_env()
    provider = os.getenv("MODEL_PROVIDER", "bailian")
    if provider not in {"bailian", "tacc"}:
        raise ValueError("MODEL_PROVIDER must be bailian or tacc")
    api_key = (
        require_env("BAILIAN_API_KEY")
        if provider == "bailian"
        else os.getenv("MODEL_API_KEY", "not-required")
    )
    thinking = (
        {"enable_thinking": False}
        if provider == "bailian"
        else {"chat_template_kwargs": {"enable_thinking": False}}
    )
    return ChatOpenAI(
        model=os.getenv("MODEL_NAME", "qwen3.8-27b"),
        base_url=require_env("MODEL_BASE_URL"),
        api_key=api_key,
        temperature=0,
        max_tokens=max_tokens,
        timeout=timeout,
        max_retries=0,
        extra_body=thinking,
        use_responses_api=False,
    )


def probe() -> dict:
    """Ask for a native tool call, execute it, and send its result back."""
    model = make_model(max_tokens=128)
    tool = {
        "type": "function",
        "function": {
            "name": "add",
            "description": "Add two integers. Use this tool for addition.",
            "parameters": {
                "type": "object",
                "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
                "required": ["a", "b"],
                "additionalProperties": False,
            },
        },
    }
    messages = [
        SystemMessage(content="Use the add tool for arithmetic. After its result, reply only 18."),
        HumanMessage(content="What is 7 + 11? Call add with a=7 and b=11 first."),
    ]
    start = time.monotonic()
    first = model.bind_tools([tool]).invoke(messages)
    if len(first.tool_calls) != 1:
        raise RuntimeError("Expected one native tool call")
    call = first.tool_calls[0]
    if call["name"] != "add" or call["args"] != {"a": 7, "b": 11}:
        raise RuntimeError("Unexpected tool name or arguments")
    result = call["args"]["a"] + call["args"]["b"]
    final = model.invoke(
        [*messages, first, ToolMessage(content=str(result), tool_call_id=call["id"])]
    )
    if final.content.strip() != "18":
        raise RuntimeError("Model did not consume the tool result correctly")
    return {
        "ok": True,
        "model": model.model_name,
        "tool_call": {"name": call["name"], "args": call["args"]},
        "tool_result": result,
        "answer": final.content,
        "usage": [first.usage_metadata, final.usage_metadata],
        "elapsed_seconds": round(time.monotonic() - start, 3),
    }


def main() -> None:
    argparse.ArgumentParser(description=__doc__).parse_args()
    try:
        print(json.dumps(probe(), ensure_ascii=False, indent=2))
    except (OpenAIError, RuntimeError, ValueError) as exc:
        # SDK exceptions may contain a credential-bearing URL or raw response.
        raise SystemExit(f"Model probe failed ({type(exc).__name__})") from None


if __name__ == "__main__":
    main()
