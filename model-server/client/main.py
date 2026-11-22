"""Exercise the deployed service from a TACC CPU node using the standard library."""
import json
import secrets
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener


def chat(url, messages, **options):
    payload = dict(model="qwen3.8-27b", messages=messages, stream=False, n=1,
                   temperature=0, max_tokens=512,
                   chat_template_kwargs={"enable_thinking": False}, **options)
    request = Request(url + "/chat/completions", json.dumps(payload).encode(),
                      {"Content-Type": "application/json", "Authorization": "Bearer EMPTY"})
    # This is a cluster-internal service, including on nodes with HTTP_PROXY set.
    with build_opener(ProxyHandler({})).open(request, timeout=120) as response:
        message = json.load(response)["choices"][0]["message"]
    return (message.get("content") or "").strip(), message.get("tool_calls") or []


def main():
    url = Path("server-url.txt").read_text().strip()
    text, calls = chat(url, [{"role": "user", "content": "Reply with exactly: connection_ok"}])
    if text != "connection_ok" or calls:
        raise ValueError("Unexpected text reply: " + repr(text))
    print("Answer:", text)
    tool = {"type": "function", "function": {"name": "get_receipt",
            "description": "Return the current verification receipt.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}}
    messages = [{"role": "user", "content": "Call get_receipt and reply with only its returned value."}]
    content, calls = chat(url, messages, tools=[tool], tool_choice="auto")
    if len(calls) != 1 or not calls[0]["id"] or calls[0]["function"]["name"] != "get_receipt":
        raise ValueError("Expected one get_receipt call: " + repr(calls))
    if json.loads(calls[0]["function"]["arguments"]) != {}:
        raise ValueError("Unexpected get_receipt arguments")
    receipt = secrets.token_hex(8)
    messages.extend([{"role": "assistant", "content": content or None, "tool_calls": calls},
                     {"role": "tool", "tool_call_id": calls[0]["id"], "content": receipt}])
    answer, more_calls = chat(url, messages, tools=[tool], tool_choice="none")
    if answer != receipt or more_calls:
        raise ValueError("Expected tool result %s, received %r" % (receipt, answer))
    print("Tool result confirmed:", answer)
    print("MODEL_SERVER_VERIFY=PASS")


if __name__ == "__main__":
    main()
