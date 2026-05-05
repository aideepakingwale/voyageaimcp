"""
Flask Request/Response Logging Middleware
Assigns a Trace ID at request start — flows through the entire call chain.
"""
import time
import uuid
from flask import Flask, request, g
from .logging_config import get_logger
from .trace import set_trace_id, new_trace_id, clear_trace_id

log = get_logger("app")


def register_request_logging(app: Flask) -> None:

    @app.before_request
    def _before():
        # Create and store trace ID for this request
        tid = new_trace_id()
        set_trace_id(tid)
        g.trace_id      = tid
        g.request_start = time.perf_counter()

        if _is_static(request.path):
            return

        log.info("REQ %s %s", request.method, request.path, extra={
            "method": request.method,
            "path":   request.path,
            "ip":     request.remote_addr,
            "ua":     request.user_agent.string[:80],
        })

    @app.after_request
    def _after(response):
        if _is_static(request.path):
            return response

        ms  = round((time.perf_counter() - g.get("request_start", 0)) * 1000)
        lvl = "warning" if response.status_code >= 400 else "info"
        getattr(log, lvl)("RES %s %s %s", response.status_code,
                           request.method, request.path, extra={
            "status":     response.status_code,
            "elapsed_ms": ms,
        })

        # Add trace ID to response header so client can correlate
        response.headers["X-Trace-Id"] = g.get("trace_id", "")
        return response

    @app.teardown_request
    def _teardown(exc):
        if exc is not None:
            log.error("Unhandled request error: %s", exc, exc_info=exc, extra={
                "path": request.path,
            })
        clear_trace_id()


def _is_static(path: str) -> bool:
    return any(path.endswith(ext)
               for ext in (".js", ".css", ".html", ".ico", ".png", ".map", ".woff"))

