from copy import deepcopy
from uuid import UUID, uuid4

from app.research.model_client import ModelCompletion
from app.tasks.lifecycle import append_event, database_time, locked_task, owns_task


class ReviewOwnershipLost(RuntimeError):
    pass


class ReviewLimitError(RuntimeError):
    pass


class ReviewStore:
    def __init__(self, sessions, task_id: UUID, owner: UUID):
        self.sessions = sessions
        self.task_id = task_id
        self.owner = owner

    def _task(self, session):
        task = locked_task(session, self.task_id)
        now = database_time(session)
        if not owns_task(task, self.owner, now):
            raise ReviewOwnershipLost("Review lease or deadline is no longer owned")
        return task, now

    def _write(self, task, state: dict) -> None:
        attempts = [attempt for unit in state["units"].values() for attempt in unit.get("attempts", [])]
        task.input_tokens = sum(attempt["input_tokens"] for attempt in attempts)
        task.output_tokens = sum(attempt["output_tokens"] for attempt in attempts)
        task.model_calls = len(attempts)
        task.tool_calls = 0
        state["usage_estimated"] = any(attempt["usage_estimated"] for attempt in attempts)
        state["usage"] = {"input_tokens": task.input_tokens, "output_tokens": task.output_tokens, "model_calls": task.model_calls}
        task.review_state = state

    def read(self) -> dict:
        with self.sessions.begin() as session:
            task, unused = self._task(session)
            return deepcopy(task.review_state)

    def reserve(self, key: str, input_tokens: int, output_tokens: int, stage: str, message: str, payload: dict) -> str:
        with self.sessions.begin() as session:
            task, now = self._task(session)
            state = deepcopy(task.review_state)
            units = state.setdefault("units", {})
            attempts = units.get(key, {}).get("attempts", [])
            all_attempts = [attempt for unit in units.values() for attempt in unit.get("attempts", [])]
            retries = sum(max(0, len(unit.get("attempts", [])) - 1) for unit in units.values())
            if len(attempts) >= 2 or (attempts and retries >= task.run_config["review_policy"]["retry_reserve"]):
                raise ReviewLimitError("Review retry allowance exhausted")
            used = sum(attempt["input_tokens"] + attempt["output_tokens"] for attempt in all_attempts)
            if len(all_attempts) >= task.max_steps or used + input_tokens + output_tokens > task.max_tokens:
                raise ReviewLimitError("Review automatic token or call allowance exhausted")
            identity = str(uuid4())
            unit = units.setdefault(key, {"attempts": []})
            unit["attempts"].append({"id": identity, "owner": str(self.owner), "status": "running",
                                     "input_tokens": input_tokens, "output_tokens": output_tokens,
                                     "usage_estimated": True, "finish_reason": None})
            self._write(task, state)
            task.stage = stage
            append_event(session, task, now, message, "stage", {"unit": key, **payload})
            return identity

    def _attempt(self, state: dict, key: str, identity: str) -> dict:
        attempt = state["units"][key]["attempts"][-1]
        if attempt["id"] != identity or attempt["owner"] != str(self.owner):
            raise ReviewOwnershipLost("Review attempt ownership changed")
        return attempt

    def settle(self, key: str, identity: str, completion: ModelCompletion | None, diagnostic: dict | None, result: dict | None = None) -> None:
        with self.sessions.begin() as session:
            task, unused = self._task(session)
            state = deepcopy(task.review_state)
            attempt = self._attempt(state, key, identity)
            if attempt["status"] != "running":
                raise ReviewOwnershipLost("Review attempt is already settled")
            if completion is not None:
                if completion.input_tokens is not None and completion.output_tokens is not None:
                    attempt.update(input_tokens=completion.input_tokens, output_tokens=completion.output_tokens, usage_estimated=False)
                attempt["finish_reason"] = completion.finish_reason
            attempt.update(status="returned" if completion else "failed", diagnostic=diagnostic)
            self._write(task, state)
            exceeded = task.input_tokens + task.output_tokens > task.max_tokens
            if result is not None and not exceeded:
                if completion is None or diagnostic is not None:
                    raise ValueError("A checkpoint requires a validated completion")
                attempt["status"] = "succeeded"
                state["units"][key]["result"] = result
                self._write(task, state)
        if exceeded:
            raise ReviewLimitError("Reported model usage exceeded the automatic allowance")

    def checkpoint(self, key: str, identity: str, result: dict) -> None:
        with self.sessions.begin() as session:
            task, unused = self._task(session)
            state = deepcopy(task.review_state)
            attempt = self._attempt(state, key, identity)
            if attempt["status"] != "returned":
                raise ReviewOwnershipLost("Review attempt has no completed response")
            attempt["status"] = "succeeded"
            state["units"][key]["result"] = result
            self._write(task, state)

    def skip(self, key: str, result: dict) -> None:
        with self.sessions.begin() as session:
            task, unused = self._task(session)
            state = deepcopy(task.review_state)
            state.setdefault("units", {})[key] = {"result": result, "attempts": []}
            self._write(task, state)

    def progress(self, stage: str, message: str) -> None:
        with self.sessions.begin() as session:
            task, now = self._task(session)
            task.stage = stage
            append_event(session, task, now, message, "stage")
