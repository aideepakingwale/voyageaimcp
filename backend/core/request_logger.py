"""
Flask Request/Response Logging Middleware
Logs every inbound HTTP request and its response to app.log.
Captures: method, path, status, duration, session_id, user identity.
"""
import time
import uuid
from flask       import Flask, request, g
from .logging_config import get_logger

log = get_logger("app")


def register_request_logging(app: Flask) -> None:
    """Attach before/after request hooks to the Flask app."""

    @app.before_request
    def _before():
        g.request_id  = str(uuid.uuid4())[:8]
        g.request_start = time.perf_counter()
        # Don't log static file requests
        if _is_static(request.path):
            return
        log.info("→ %s %s", request.method, request.path, extra={
            "request_id":  g.request_id,
            "method":      request.method,
            "path":        request.path,
            "ip":          request.remote_addr,
            "user_agent":  request.user_agent.string[:80],
        })

    @app.after_request
    def _after(response):
        if _is_static(request.path):
            return response
        elapsed_ms = round((time.perf_counter() - g.get("request_start", 0)) * 1000)
        level = "warning" if response.status_code >= 400 else "info"
        getattr(log, level)("← %s %s %s", response.status_code,
                             request.method, request.path, extra={
            "request_id":  g.get("request_id",""),
            "status":      response.status_code,
            "method":      request.method,
            "path":        request.path,
            "elapsed_ms":  elapsed_ms,
            "content_len": response.content_length,
        })
        return response

    @app.teardown_request
    def _teardown(exc):
        if exc is not None:
            log.error("Request error: %s", exc, exc_info=exc, extra={
                "request_id": g.get("request_id",""),
                "path":       request.path,
            })


def _is_static(path: str) -> bool:
    """Skip logging for frontend static file requests."""
    return any(path.endswith(ext)
               for ext in (".js",".css",".html",".ico",".png",".jpg",".map"))
