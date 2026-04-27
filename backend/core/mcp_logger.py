"""
MCP Call Logger
===============
Wraps BaseMCP._fetch() to log every downstream tool call:

  mcp.log line example:
  {
    "ts": "2025-10-01T09:15:23Z",
    "level": "INFO",
    "logger": "voyage.mcp",
    "message": "MCP CALL",
    "server": "flights",
    "params": {"origin":"LHR","destination":"LIS","date":"2025-10-01"},
    "source": "amadeus_live",
    "confidence": 0.97,
    "elapsed_ms": 312.4,
    "count": 5,
    "request_id": "a3f1b2c4"
  }

Usage: Applied automatically in BaseMCP — no changes needed per server.
"""
import time
import functools
from core.logging_config import get_logger
from core.request_context import get_request_id

log = get_logger("mcp")

# Keys to redact from logged params
_REDACT = {"api_key","token","secret","password","card","cvv"}


def log_mcp_call(server_name: str, params: dict,
                 result: dict, elapsed_ms: float) -> None:
    """Log a completed MCP server call."""
    data    = result.get("data", {}) if isinstance(result.get("data"), dict) else {}
    source  = data.get("source", result.get("source", "unknown"))
    conf    = result.get("confidence", 0)
    count   = result.get("count", _count_items(data))
    error   = result.get("error")
    cached  = result.get("cached", False)

    level = log.warning if error else log.info

    safe_params = {
        k: ("***" if any(r in k.lower() for r in _REDACT) else v)
        for k, v in (params or {}).items()
    }

    level("MCP CALL",
          extra={
              "request_id": get_request_id(),
              "server":     server_name,
              "params":     safe_params,
              "source":     source,
              "confidence": round(conf, 3),
              "elapsed_ms": elapsed_ms,
              "count":      count,
              "cached":     cached,
              "error":      error,
          })


def _count_items(data: dict) -> int:
    """Count the main result items in an MCP response."""
    for key in ("flights","hotels","options","experiences","ancillaries"):
        val = data.get(key)
        if isinstance(val, list):
            return len(val)
    return 1 if data else 0
