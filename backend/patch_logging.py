"""
VoyageAI Logging Patch Script
Run this once from the backend folder to fix the ImportError:

  cd D:\...\voyageai\backend
  python patch_logging.py

This writes the correct core/__init__.py and core/logging_config.py
and also creates core/request_logger.py if it is missing.
"""
import os, sys
from pathlib import Path

HERE   = Path(__file__).parent
CORE   = HERE / "core"
CORE.mkdir(exist_ok=True)

# ── 1. core/__init__.py ───────────────────────────────────────
(CORE / "__init__.py").write_text(
    '"""VoyageAI core utilities."""\n'
    'from .logging_config  import init_logging, get_logger\n'
    'from .request_logger  import register_request_logging\n'
    '\n'
    '__all__ = ["init_logging", "get_logger", "register_request_logging"]\n',
    encoding="utf-8"
)
print("✓ core/__init__.py written")

# ── 2. core/logging_config.py ────────────────────────────────
LOGGING_CONFIG = r'''"""
VoyageAI Logging Configuration — creates separate rotating log files.

  logs/
  ├── app.log          Flask HTTP requests + session events
  ├── llm.log          LLM waterfall calls (provider, latency, tokens, cost)
  ├── mcp.log          MCP server calls (live vs fallback, confidence)
  ├── guardrails.log   Guardrail layer decisions
  ├── auth.log         Login / logout events
  ├── errors.log       ALL errors from every module
  └── debug.log        Full verbose (set LOG_LEVEL=DEBUG in .env)

Usage:
    from core.logging_config import get_logger
    log = get_logger("mcp.flights")
    log.info("Search", extra={"results": 5, "source": "live", "ms": 230})
"""
import os, sys, json, logging, logging.handlers, threading
from datetime import datetime, timezone
from pathlib  import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent
LOG_DIR       = _BACKEND_DIR.parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

_DEBUG_MODE = os.getenv("LOG_LEVEL", "INFO").upper() == "DEBUG"
_done       = False
_lock       = threading.Lock()


class JSONFormatter(logging.Formatter):
    _SKIP = {
        "name","msg","args","levelname","levelno","pathname","filename","module",
        "exc_info","exc_text","stack_info","lineno","funcName","created","msecs",
        "relativeCreated","thread","threadName","processName","process",
        "message","taskName",
    }
    def format(self, r):
        obj = {
            "ts":     datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]+"Z",
            "level":  r.levelname,
            "logger": r.name,
            "msg":    r.getMessage(),
        }
        ctx = {k: v for k, v in r.__dict__.items() if k not in self._SKIP}
        if ctx:        obj["ctx"] = ctx
        if r.exc_info: obj["exc"] = self.formatException(r.exc_info)
        return json.dumps(obj, default=str)


class ConsoleFormatter(logging.Formatter):
    _C = {
        "DEBUG":    "\033[36m",
        "INFO":     "\033[32m",
        "WARNING":  "\033[33m",
        "ERROR":    "\033[31m",
        "CRITICAL": "\033[35m",
    }
    _R = "\033[0m"
    _SKIP = {
        "name","msg","args","levelname","levelno","pathname","filename","module",
        "exc_info","exc_text","stack_info","lineno","funcName","created","msecs",
        "relativeCreated","thread","threadName","processName","process",
        "message","taskName",
    }
    def format(self, r):
        c   = self._C.get(r.levelname, "")
        ts  = datetime.now().strftime("%H:%M:%S")
        ctx = {k: v for k, v in r.__dict__.items() if k not in self._SKIP}
        suf = f"  {json.dumps(ctx, default=str)}" if ctx else ""
        out = f"{ts} {c}{r.levelname:<8}{self._R} [{r.name}] {r.getMessage()}{suf}"
        if r.exc_info:
            out += "\n" + self.formatException(r.exc_info)
        return out


def _rot_handler(filename, level=logging.DEBUG, mb=5, bk=5):
    h = logging.handlers.RotatingFileHandler(
        LOG_DIR / filename,
        maxBytes=mb * 1024 * 1024,
        backupCount=bk,
        encoding="utf-8",
    )
    h.setLevel(level)
    h.setFormatter(JSONFormatter())
    return h


def _console_handler():
    h = logging.StreamHandler(sys.stdout)
    h.setLevel(logging.DEBUG if _DEBUG_MODE else logging.INFO)
    h.setFormatter(ConsoleFormatter())
    return h


_SUBSYSTEMS = {
    "voyageai.app":        "app.log",
    "voyageai.llm":        "llm.log",
    "voyageai.mcp":        "mcp.log",
    "voyageai.guardrails": "guardrails.log",
    "voyageai.rag":        "rag.log",
    "voyageai.auth":       "auth.log",
    "voyageai.reasoning":  "app.log",
}


def init_logging() -> None:
    """Call once at app startup. Thread-safe, idempotent."""
    global _done
    with _lock:
        if _done:
            return
        _done = True

    err_handler = _rot_handler("errors.log", level=logging.ERROR)

    root = logging.getLogger()
    root.setLevel(logging.WARNING)
    root.addHandler(err_handler)

    for prefix, filename in _SUBSYSTEMS.items():
        lg = logging.getLogger(prefix)
        lg.setLevel(logging.DEBUG)
        lg.propagate = False
        lg.addHandler(_rot_handler(filename))
        lg.addHandler(_console_handler())
        lg.addHandler(err_handler)

    if _DEBUG_MODE:
        dbg = logging.getLogger("voyageai")
        dbg.setLevel(logging.DEBUG)
        dbg.addHandler(_rot_handler("debug.log", level=logging.DEBUG))

    wz = logging.getLogger("werkzeug")
    wz.setLevel(logging.INFO)
    wz.propagate = False
    wz.addHandler(_rot_handler("app.log", level=logging.INFO))
    wz.addHandler(_console_handler())

    for lib in ("urllib3","requests","httpcore","httpx","google",
                "anthropic._base_client","groq._base_client","openai"):
        logging.getLogger(lib).setLevel(logging.ERROR)

    print(f"\n  \u2713 Logs \u2192 {LOG_DIR}")
    print(f"    Files: app \u00b7 llm \u00b7 mcp \u00b7 guardrails \u00b7 auth \u00b7 errors"
          + (" \u00b7 debug" if _DEBUG_MODE else ""))


def get_logger(name: str) -> logging.Logger:
    """
    Get a named logger under the voyageai namespace.
    'voyageai.' is added automatically.
    Examples:
        get_logger("mcp.flights")   -> mcp.log
        get_logger("llm.waterfall") -> llm.log
        get_logger("auth")          -> auth.log
    """
    full = f"voyageai.{name}" if not name.startswith("voyageai") else name
    return logging.getLogger(full)


# Alias so both names work
setup_logging = init_logging
'''

(CORE / "logging_config.py").write_text(LOGGING_CONFIG, encoding="utf-8")
print("✓ core/logging_config.py written")

# ── 3. core/request_logger.py ─────────────────────────────────
REQUEST_LOGGER = '''"""Flask request/response logging middleware."""
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
'''

(CORE / "request_logger.py").write_text(REQUEST_LOGGER, encoding="utf-8")
print("✓ core/request_logger.py written")

# ── 4. Quick smoke test ───────────────────────────────────────
print("\nRunning smoke test...")
sys.path.insert(0, str(HERE))

from core import init_logging, get_logger, register_request_logging
init_logging()

log = get_logger("app")
log.info("Patch applied successfully", extra={"version": "v7"})

LOG_DIR = HERE.parent / "logs"
files   = sorted(p.name for p in LOG_DIR.iterdir() if p.suffix == ".log")
print(f"\n✓ Log files present: {', '.join(files)}")
print("\n✓ All good — run:  python run.py")
