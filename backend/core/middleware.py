"""
Flask API Logging Middleware
============================
Logs every incoming request and outgoing response to api.log:

  → POST /api/chat  session=a1b2c3  customer=CUST001
  ← 200  POST /api/chat  elapsed=1842ms  status=ready  provider=groq

Also sets a unique X-Request-ID header on every response so
front-end developers can correlate browser network logs with server logs.
"""
import time
from flask import Flask, request, g, Response
from core.logging_config import get_logger
from core.request_context import set_request_id, get_request_id, get_elapsed_ms

log = get_logger("api")

# Paths to skip logging (health polling etc.)
SKIP_PATHS = {"/api/health", "/favicon.ico", "/api/waterfall"}


def register_middleware(app: Flask) -> None:
    """Attach before/after request hooks to the Flask app."""

    @app.before_request
    def before():
        if request.path in SKIP_PATHS:
            return

        rid = request.headers.get("X-Request-ID") or set_request_id()
        g.request_id   = rid
        g.request_start= time.perf_counter()

        # Extract useful context from body without consuming it
        body_preview = ""
        if request.content_type and "json" in request.content_type:
            try:
                data = request.get_json(silent=True, cache=True) or {}
                body_preview = _safe_preview(data)
            except Exception:
                pass

        log.info("→ REQUEST",
                 extra={
                     "request_id": rid,
                     "method":     request.method,
                     "path":       request.path,
                     "remote_ip":  request.remote_addr,
                     "user_agent": request.user_agent.string[:80],
                     "body":       body_preview,
                 })

    @app.after_request
    def after(response: Response) -> Response:
        if request.path in SKIP_PATHS:
            return response

        rid     = getattr(g, "request_id", get_request_id())
        start   = getattr(g, "request_start", time.perf_counter())
        elapsed = round((time.perf_counter() - start) * 1000, 1)

        # Add request ID to response headers
        response.headers["X-Request-ID"]    = rid
        response.headers["X-Elapsed-Ms"]    = str(elapsed)

        # Log response summary
        level = log.error if response.status_code >= 500 else \
                log.warning if response.status_code >= 400 else log.info

        resp_preview = ""
        try:
            if "json" in (response.content_type or ""):
                import json
                data = json.loads(response.get_data(as_text=True))
                resp_preview = _safe_preview(data, keys=["status","llm_provider","error","message"])
        except Exception:
            pass

        level("← RESPONSE",
              extra={
                  "request_id":  rid,
                  "method":      request.method,
                  "path":        request.path,
                  "status_code": response.status_code,
                  "elapsed_ms":  elapsed,
                  "response":    resp_preview,
                  "size_bytes":  response.content_length,
              })
        return response

    @app.errorhandler(Exception)
    def handle_exception(exc: Exception) -> Response:
        import traceback
        rid = getattr(g, "request_id", get_request_id())
        log.error("UNHANDLED EXCEPTION",
                  exc_info=True,
                  extra={
                      "request_id": rid,
                      "path":       request.path,
                      "method":     request.method,
                      "exception":  type(exc).__name__,
                      "detail":     str(exc),
                  })
        return Response(
            '{"error":"Internal server error","request_id":"' + rid + '"}',
            status=500,
            mimetype="application/json",
        )


def _safe_preview(data: dict, keys: list = None, max_len: int = 120) -> str:
    """Extract key fields from a dict for log preview without exposing secrets."""
    SENSITIVE = {"password","token","api_key","member_id","email","secret"}
    if not isinstance(data, dict):
        return str(data)[:max_len]

    pick = keys or list(data.keys())[:6]
    parts = []
    for k in pick:
        if k in data:
            v = data[k]
            if any(s in k.lower() for s in SENSITIVE):
                v = "***"
            elif isinstance(v, str) and len(v) > 40:
                v = v[:40] + "…"
            elif isinstance(v, dict):
                v = "{…}"
            parts.append(f"{k}={v!r}")
    return "  ".join(parts)[:max_len]
