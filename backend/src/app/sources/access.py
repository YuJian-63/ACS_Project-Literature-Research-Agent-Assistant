import copy
import math
import time
from collections import OrderedDict
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from threading import Lock
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.sources.arxiv import ArxivError, ArxivPage, build_search_query
from app.db.models import SourceRequestGate


@dataclass(frozen=True)
class SourcePermit:
    provider: str
    owner_id: UUID
    lease_expires_at: datetime


def acquire_source_permit(sessions: sessionmaker[Session], provider: str) -> SourcePermit | None:
    if provider != "arxiv":
        raise ValueError("Unsupported source provider")
    with sessions.begin() as session:
        gate = session.scalar(select(SourceRequestGate).where(SourceRequestGate.provider == provider).with_for_update(skip_locked=True))
        if gate is None:
            return None
        now = session.scalar(select(func.clock_timestamp()))
        if gate.next_allowed_at > now or (gate.blocked_until is not None and gate.blocked_until > now):
            return None
        if gate.owner_id is not None and gate.lease_expires_at + timedelta(seconds=3) > now:
            return None
        owner_id = uuid4()
        expires = now + timedelta(seconds=120)
        gate.owner_id = owner_id
        gate.lease_expires_at = expires
        return SourcePermit(provider, owner_id, expires)


def release_source_permit(sessions: sessionmaker[Session], permit: SourcePermit, retry_after: int | None = None) -> None:
    if retry_after is not None and type(retry_after) is not int:
        raise ValueError("Invalid source cooldown")
    with sessions.begin() as session:
        gate = session.scalar(select(SourceRequestGate).where(SourceRequestGate.provider == permit.provider).with_for_update())
        if gate is None or gate.owner_id != permit.owner_id:
            return
        now = session.scalar(select(func.clock_timestamp()))
        gate.owner_id = None
        gate.lease_expires_at = None
        gate.next_allowed_at = max(gate.next_allowed_at, now + timedelta(seconds=3))
        if retry_after is not None:
            blocked = now + timedelta(seconds=max(3, min(86400, retry_after)))
            gate.blocked_until = max(gate.blocked_until, blocked) if gate.blocked_until else blocked


def source_wait_seconds(sessions: sessionmaker[Session]) -> int:
    with sessions() as session:
        gate = session.get(SourceRequestGate, "arxiv")
        now = session.scalar(select(func.clock_timestamp()))
        if gate is None:
            return 3
        targets = [gate.next_allowed_at]
        if gate.blocked_until is not None:
            targets.append(gate.blocked_until)
        if gate.lease_expires_at is not None:
            targets.append(gate.lease_expires_at + timedelta(seconds=3))
        return max(1, min(86400, math.ceil((max(targets) - now).total_seconds())))


@contextmanager
def source_permit(sessions: sessionmaker[Session]):
    permit = acquire_source_permit(sessions, "arxiv")
    if permit is None:
        raise ArxivError("ARXIV_RATE_LIMITED", "arXiv 访问额度暂不可用，请稍后重试", retryable=True,
                         retry_after=source_wait_seconds(sessions), phase="source_gate")
    delay = None

    def cooldown(seconds: int) -> None:
        nonlocal delay
        if type(seconds) is not int:
            raise ValueError("Invalid source cooldown")
        seconds = max(3, min(86400, seconds))
        delay = max(delay, seconds) if delay is not None else seconds

    try:
        yield cooldown
    finally:
        release_source_permit(sessions, permit, delay)


class SearchCache:
    def __init__(self, *, clock: Callable[[], float] = time.monotonic):
        self.clock = clock
        self.lock = Lock()
        self.entries: OrderedDict[tuple[str, int, int], tuple[float, ArxivPage]] = OrderedDict()

    def key(self, q: str, limit: int, offset: int) -> tuple[str, int, int]:
        normalized, _ = build_search_query(q)
        if type(limit) is not int or not 1 <= limit <= 20 or type(offset) is not int or not 0 <= offset <= 1000:
            raise ValueError("Invalid search pagination")
        return normalized, limit, offset

    def get(self, q: str, limit: int, offset: int) -> ArxivPage | None:
        key = self.key(q, limit, offset)
        with self.lock:
            cached = self.entries.get(key)
            if cached is None:
                return None
            if self.clock() >= cached[0]:
                del self.entries[key]
                return None
            self.entries.move_to_end(key)
            return copy.deepcopy(cached[1])

    def put(self, q: str, limit: int, offset: int, page: ArxivPage) -> None:
        key = self.key(q, limit, offset)
        if not isinstance(page, ArxivPage):
            raise ValueError("Only successful upstream pages can be cached")
        with self.lock:
            self.entries[key] = (self.clock() + 600, copy.deepcopy(page))
            self.entries.move_to_end(key)
            while len(self.entries) > 100:
                self.entries.popitem(last=False)
