from typing import Any


class APIError(Exception):
    def __init__(
        self, status_code: int, code: str, message: str, details: dict[str, Any] | None = None
    ) -> None:
        self.status_code = status_code
        self.error = {"code": code, "message": message, "details": details or {}}
        super().__init__(code)
