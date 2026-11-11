from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit

import httpx
from pydantic import SecretStr


class ModelProviderError(RuntimeError):
    pass


class ModelTimeoutError(ModelProviderError):
    pass


@dataclass(frozen=True)
class ModelCompletion:
    content: str
    input_tokens: int | None
    output_tokens: int | None


class ChatModel(Protocol):
    def complete(self, messages: list[dict[str, str]], *, model_id: str, max_tokens: int, timeout_seconds: float) -> ModelCompletion: ...

    def close(self) -> None: ...

    def close(self) -> None: ...


class OpenAICompatibleChatModel:
    def __init__(self, base_url: str, api_key: SecretStr, client: httpx.Client | None = None) -> None:
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Invalid model service base URL")
        path = parsed.path.rstrip("/")
        if path.endswith("/chat/completions"):
            endpoint_path = path
        elif path.endswith("/v1"):
            endpoint_path = path + "/chat/completions"
        else:
            endpoint_path = path + "/v1/chat/completions"
        self.endpoint = urlunsplit((parsed.scheme, parsed.netloc, endpoint_path, "", ""))
        self.api_key = api_key
        self.client = client or httpx.Client()
        self.owns_client = client is None

    def complete(self, messages: list[dict[str, str]], *, model_id: str, max_tokens: int, timeout_seconds: float) -> ModelCompletion:
        if not messages or not model_id or type(max_tokens) is not int or max_tokens < 1:
            raise ValueError("Invalid model request")
        try:
            response = self.client.post(
                self.endpoint,
                headers={"Authorization": f"Bearer {self.api_key.get_secret_value()}"},
                json={"model": model_id, "messages": messages, "max_tokens": max_tokens, "temperature": 0,
                      "response_format": {"type": "json_object"}},
                timeout=timeout_seconds,
            )
        except httpx.TimeoutException as error:
            raise ModelTimeoutError("Model service timed out") from error
        except httpx.HTTPError as error:
            raise ModelProviderError("Model service request failed") from error
        if response.is_error:
            raise ModelProviderError(f"Model service returned HTTP {response.status_code}")
        try:
            payload = response.json()
            message = payload["choices"][0]["message"]["content"]
            usage = payload.get("usage") or {}
        except (ValueError, KeyError, IndexError, TypeError) as error:
            raise ModelProviderError("Model service returned an invalid response") from error
        if not isinstance(message, str) or not message.strip():
            raise ModelProviderError("Model service returned empty content")
        return ModelCompletion(message, self._usage_count(usage.get("prompt_tokens")), self._usage_count(usage.get("completion_tokens")))

    @staticmethod
    def _usage_count(value: object) -> int | None:
        return value if type(value) is int and value >= 0 else None

    def close(self) -> None:
        if self.owns_client:
            self.client.close()
