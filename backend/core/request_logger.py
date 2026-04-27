"""Flask request/response logging middleware."""
import time, uuid
from flask import Flask, request, g
from .logging_config import get_logger

log = get_logger("app")


def register_request_logging(app: Flask) -> None:
    @app.before_request
    def _before():
        g.request_id    = str(uuid.uuid4())[:8]
        g.request_start = time.perf_counter()
        if _is_static(request.path):
            return
        log.info("-> %s %s", request.method, request.path, extra={
            "request_id": g.request_id,
            "method":     request.method,
            "path":       request.path,
            "ip":         request.remote_addr,
        })

    @app.after_request
    def _after(response):
        if _is_static(request.path):
            return response
        ms    = round((time.perf_counter() - g.get("request_start", 0)) * 1000)
        level = "warning" if response.status_code >= 400 else "info"
        getattr(log, level)(
            "<- %s %s %s", response.status_code, request.method, request.path,
            extra={
                "request_id": g.get("request_id", ""),
                "status":     response.status_code,
                "elapsed_ms": ms,
            }
        )
        return response

    @app.teardown_request
    def _teardown(exc):
        if exc is not None:
            log.error("Request error: %s", exc, exc_info=exc, extra={
                "request_id": g.get("request_id",""),
                "path":       request.path,
            })


def _is_static(path: str) -> bool:
    return any(path.endswith(ext)
               for ext in (".js", ".css", ".html", ".ico", ".png", ".map"))
