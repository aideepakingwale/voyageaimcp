"""
VoyageAI Trace Context
Maintains a per-request Trace ID that flows end-to-end through:
  HTTP request → reasoning engine → MCP calls → LLM → guardrails → response

Usage:
    from core.trace import set_trace_id, get_trace_id, new_trace_id

    # At request start:
    set_trace_id(new_trace_id())

    # Anywhere in the call chain:
    tid = get_trace_id()   # same ID throughout the request
"""
import uuid
import threading

_local = threading.local()


def new_trace_id() -> str:
    """Generate a new short trace ID."""
    return "TRC-" + str(uuid.uuid4())[:8].upper()


def set_trace_id(tid: str) -> str:
    _local.trace_id = tid
    return tid


def get_trace_id() -> str:
    return getattr(_local, "trace_id", "NO-TRACE")


def clear_trace_id():
    _local.trace_id = None
