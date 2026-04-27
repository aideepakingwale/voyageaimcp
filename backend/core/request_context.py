"""Request context — unique request_id propagated through all log calls."""
import uuid, time, logging
from contextvars import ContextVar
from typing import Optional

_request_id:    ContextVar[Optional[str]]   = ContextVar("request_id",    default=None)
_request_start: ContextVar[Optional[float]] = ContextVar("request_start", default=None)


def set_request_id(rid: str = None) -> str:
    rid = rid or str(uuid.uuid4())[:12]
    _request_id.set(rid)
    _request_start.set(time.perf_counter())
    return rid


def get_request_id() -> str:
    return _request_id.get() or "no-request"


def get_elapsed_ms() -> float:
    s = _request_start.get()
    return round((time.perf_counter() - s) * 1000, 1) if s else 0.0


def clear_request_id():
    _request_id.set(None)
    _request_start.set(None)


class RequestIdFilter(logging.Filter):
    def filter(self, record) -> bool:
        record.request_id = get_request_id()
        record.elapsed_ms = get_elapsed_ms()
        return True
