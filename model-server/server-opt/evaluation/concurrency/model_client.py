"""Standard-library client for the course's OpenAI-compatible text service."""
from dataclasses import dataclass
import json
import os
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, ProxyHandler, build_opener


class ServiceError(RuntimeError):
    """A network, HTTP, or model protocol failure; requests are never retried."""


def normalize_base_url(value):
    url = (value or "").strip().rstrip("/")
    try:
        parts = urlsplit(url)
        valid = (parts.scheme in ("http", "https") and parts.hostname
                 and parts.hostname.upper() != "NODE" and parts.path == "/v1"
                 and not parts.query and not parts.fragment
                 and parts.username is None and parts.password is None
                 and parts.port != 0 and not any(c.isspace() for c in url))
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("Set QWEN_BASE_URL to the current SERVICE_BASE_URL, "
                         "e.g. http://compute-node:8000/v1; replace NODE.")
    return url


@dataclass
class ChatResult:
    response: dict
    elapsed_s: float
    ttft_s: float = None
    tpot_s: float = None
    request_id_header: str = None

    @property
    def message(self):
        return self.response["choices"][0]["message"]

    @property
    def content(self):
        return self.message.get("content") or ""

    @property
    def usage(self):
        return self.response.get("usage") or {}


def sse_events(response):
    """Decode SSE events, ignoring comments/role-only events at the caller."""
    data = []
    for raw_line in response:
        line = raw_line.decode("utf-8").rstrip("\r\n")
        if not line:
            if data:
                yield "\n".join(data)
                data = []
        elif line.startswith("data:"):
            data.append(line[5:].lstrip(" "))
    if data:
        yield "\n".join(data)


class ModelClient:
    def __init__(self, base_url=None, model=None, timeout=300, api_key=None):
        self.base_url = normalize_base_url(base_url or os.getenv("QWEN_BASE_URL"))
        self.model = model or os.getenv("QWEN_MODEL", "qwen3.8-27b")
        self.timeout = float(timeout)
        if self.timeout <= 0:
            raise ValueError("timeout must be positive")
        self.api_key = api_key if api_key is not None else os.getenv("QWEN_API_KEY")

    def _open(self, url, payload=None):
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = "Bearer " + self.api_key
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(url, data=data, headers=headers)
        # TACC service traffic is internal. Ignore inherited HTTP proxy settings.
        return build_opener(ProxyHandler({})).open(request, timeout=self.timeout)

    def get_text(self, path, *, server_root=False):
        base = self.base_url[:-3] if server_root else self.base_url
        try:
            with self._open(base + "/" + path.lstrip("/")) as response:
                return response.read().decode("utf-8")
        except (HTTPError, URLError, OSError, ValueError) as exc:
            raise ServiceError(f"GET {path} failed: {exc}") from exc

    def models(self):
        try:
            return json.loads(self.get_text("models"))
        except ValueError as exc:
            raise ServiceError("/v1/models returned invalid JSON") from exc

    def chat(self, messages, *, stream=False, max_tokens=512,
             temperature=0.0, on_event=None, **extra):
        """Return an assembled response; preserve tool_calls and usage.

        stream=True consumes SSE to measure client-observed TTFT/TPOT. It does
        not yield UI events. No automatic retries: callers own retry budgets.
        """
        if not isinstance(messages, list) or not messages:
            raise ValueError("messages must be a nonempty list")
        if max_tokens < 1:
            raise ValueError("max_tokens must be positive")
        payload = dict(extra)
        payload.update(model=self.model, messages=messages, stream=stream,
                       max_tokens=max_tokens, temperature=temperature)
        payload.setdefault("chat_template_kwargs", {"enable_thinking": False})
        if stream:
            payload["stream_options"] = {"include_usage": True}
        started = time.perf_counter()
        try:
            with self._open(self.base_url + "/chat/completions", payload) as response:
                request_id_header = response.headers.get("X-Request-Id")
                if stream:
                    result = self._consume_stream(response, started, on_event)
                    result.request_id_header = request_id_header
                    return result
                result = json.load(response)
                elapsed = time.perf_counter() - started
                message = result["choices"][0]["message"]
                if not isinstance(message.get("content"), str) and not message.get("tool_calls"):
                    raise ServiceError("Response has neither text nor tool_calls")
                return ChatResult(result, elapsed, request_id_header=request_id_header)
        except HTTPError as exc:
            body = exc.read(1500).decode("utf-8", errors="replace")
            raise ServiceError(f"HTTP {exc.code}: {body}") from exc
        except (URLError, OSError) as exc:
            raise ServiceError("Service unreachable or timed out; check the current "
                               f"job, startup log, and URL. Details: {exc}") from exc
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ServiceError(f"Invalid service response: {exc}") from exc

    @staticmethod
    def _consume_stream(response, started, on_event=None):
        content, reasoning, calls = [], [], {}
        first = last = None
        usage, finish, response_id, response_model = {}, None, None, None
        server_metrics = None
        done = False
        for event in sse_events(response):
            if on_event is not None:
                on_event(event)
            if event == "[DONE]":
                done = True
                break
            chunk = json.loads(event)
            arrived = time.perf_counter()
            if chunk.get("error"):
                raise ServiceError(f"Stream error: {chunk['error']}")
            response_id = chunk.get("id", response_id)
            response_model = chunk.get("model", response_model)
            if chunk.get("usage"):
                usage = chunk["usage"]
            if chunk.get("metrics") is not None:
                server_metrics = chunk["metrics"]
            for choice in chunk.get("choices", []):
                if choice.get("index", 0) != 0:
                    continue
                delta = choice.get("delta") or {}
                text = delta.get("content") or ""
                thought = delta.get("reasoning") or delta.get("reasoning_content") or ""
                tool_deltas = delta.get("tool_calls") or []
                generated = bool(text or thought or any(
                    d.get("function", {}).get("name") or d.get("function", {}).get("arguments")
                    for d in tool_deltas))
                if generated:
                    if first is None:
                        first = arrived
                    last = arrived
                content.append(text)
                reasoning.append(thought)
                for part in tool_deltas:
                    target = calls.setdefault(part["index"], {
                        "id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                    for key in ("id", "type"):
                        if part.get(key):
                            target[key] = part[key]
                    for key in ("name", "arguments"):
                        target["function"][key] += part.get("function", {}).get(key) or ""
                if choice.get("finish_reason") is not None:
                    finish = choice["finish_reason"]
        if not done or finish is None or first is None:
            raise ServiceError("Incomplete SSE response (missing generation, finish_reason, or DONE)")
        message = {"role": "assistant", "content": "".join(content) or None}
        if calls:
            message["tool_calls"] = [calls[i] for i in sorted(calls)]
        if any(reasoning):
            message["reasoning"] = "".join(reasoning)
        tokens = usage.get("completion_tokens")
        tpot = ((last - first) / (tokens - 1)
                if isinstance(tokens, int) and tokens > 1 else None)
        result = {"id": response_id, "model": response_model, "usage": usage,
                  "choices": [{"index": 0, "message": message, "finish_reason": finish}]}
        if server_metrics is not None:
            result["metrics"] = server_metrics
        return ChatResult(result, time.perf_counter() - started, first - started, tpot)
