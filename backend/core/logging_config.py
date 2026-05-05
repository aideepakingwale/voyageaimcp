"""
VoyageAI Logging Configuration
Separate rotating log files per subsystem + Trace ID on every line.

  logs/
  ├── app.log          Flask HTTP requests, sessions, auth events
  ├── llm.log          LLM calls: provider, model, latency, tokens, cost
  │                    + FULL prompt and response in debug.log
  ├── mcp.log          MCP server calls: source, confidence, latency
  ├── guardrails.log   Guardrail decisions: layer, pass/fail, reason
  ├── auth.log         Login / logout events
  ├── errors.log       ALL errors from every module
  └── debug.log        Full verbose including complete LLM prompts/responses
                       (set LOG_LEVEL=DEBUG in .env to enable)

Every log line includes:
  ts       — ISO-8601 timestamp with milliseconds
  level    — DEBUG / INFO / WARNING / ERROR
  logger   — voyageai.mcp.FlightMCP etc.
  trace_id — end-to-end trace ID for the current request (e.g. TRC-A3F1B2C4)
  msg      — log message
  ctx      — arbitrary key-value context (NEVER truncated)
"""
import os, sys, json, logging, logging.handlers, threading
from datetime import datetime, timezone
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent
LOG_DIR       = _BACKEND_DIR.parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

_DEBUG_MODE = os.getenv("LOG_LEVEL", "INFO").upper() == "DEBUG"
_done, _lock = False, threading.Lock()


def _get_trace_id() -> str:
    """Get the current trace ID without creating a circular import."""
    try:
        from core.trace import get_trace_id
        return get_trace_id()
    except Exception:
        return ""


class JSONFormatter(logging.Formatter):
    """One JSON object per line — full context, never truncated."""
    _SKIP = {
        "name","msg","args","levelname","levelno","pathname","filename","module",
        "exc_info","exc_text","stack_info","lineno","funcName","created","msecs",
        "relativeCreated","thread","threadName","processName","process",
        "message","taskName",
    }

    def format(self, r: logging.LogRecord) -> str:
        tid = _get_trace_id()
        obj = {
            "ts":       datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "level":    r.levelname,
            "logger":   r.name,
            "trace_id": tid,
            "msg":      r.getMessage(),
        }
        # Attach all extra context — no truncation
        ctx = {k: v for k, v in r.__dict__.items() if k not in self._SKIP}
        if ctx:
            obj["ctx"] = ctx
        if r.exc_info:
            obj["exc"] = self.formatException(r.exc_info)
        return json.dumps(obj, default=str, ensure_ascii=False)


class ConsoleFormatter(logging.Formatter):
    """Coloured terminal output with trace ID on every line."""
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

    def format(self, r: logging.LogRecord) -> str:
        c   = self._C.get(r.levelname, "")
        ts  = datetime.now().strftime("%H:%M:%S")
        tid = _get_trace_id()
        tid_str = f" [{tid}]" if tid and tid != "NO-TRACE" else ""

        ctx = {k: v for k, v in r.__dict__.items() if k not in self._SKIP}
        # Show full context on console in debug mode; summarise in info mode
        if ctx and _DEBUG_MODE:
            suf = f"\n          {json.dumps(ctx, default=str, ensure_ascii=False, indent=2)}"
        elif ctx:
            # One-line summary for INFO level
            suf = "  " + json.dumps(ctx, default=str, ensure_ascii=False)
        else:
            suf = ""

        out = f"{ts}{tid_str} {c}{r.levelname:<8}{self._R} [{r.name}] {r.getMessage()}{suf}"
        if r.exc_info:
            out += "\n" + self.formatException(r.exc_info)
        return out


def _rot(fname: str, level=logging.DEBUG, mb: int = 10, bk: int = 5):
    h = logging.handlers.RotatingFileHandler(
        LOG_DIR / fname, maxBytes=mb * 1024 * 1024,
        backupCount=bk, encoding="utf-8"
    )
    h.setLevel(level)
    h.setFormatter(JSONFormatter())
    return h


def _con():
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
    """Idempotent, thread-safe logging setup."""
    global _done
    with _lock:
        if _done:
            return
        _done = True

    err_handler = _rot("errors.log", level=logging.ERROR, mb=20)

    root = logging.getLogger()
    root.setLevel(logging.WARNING)
    root.addHandler(err_handler)

    for prefix, fname in _SUBSYSTEMS.items():
        lg = logging.getLogger(prefix)
        lg.setLevel(logging.DEBUG)
        lg.propagate = False
        lg.addHandler(_rot(fname))
        lg.addHandler(_con())
        lg.addHandler(err_handler)

    # debug.log — full verbose including complete LLM prompts and responses
    if _DEBUG_MODE:
        dbg = logging.getLogger("voyageai")
        dbg.setLevel(logging.DEBUG)
        dbg.addHandler(_rot("debug.log", level=logging.DEBUG, mb=50, bk=10))

    # Werkzeug → app.log
    wz = logging.getLogger("werkzeug")
    wz.setLevel(logging.INFO)
    wz.propagate = False
    wz.addHandler(_rot("app.log", level=logging.INFO))
    wz.addHandler(_con())

    # Silence noisy third-party libs
    for lib in ("urllib3", "requests", "httpcore", "httpx", "google",
                "anthropic._base_client", "groq._base_client", "openai"):
        logging.getLogger(lib).setLevel(logging.ERROR)

    print(f"\n  Logs -> {LOG_DIR}")
    mode = "DEBUG (full LLM prompts in debug.log)" if _DEBUG_MODE else "INFO"
    print(f"    Level: {mode}")
    print(f"    Files: app, llm, mcp, guardrails, auth, errors"
          + (", debug" if _DEBUG_MODE else ""))


def get_logger(name: str) -> logging.Logger:
    """
    Get a named VoyageAI logger with trace ID on every line.
    'voyageai.' prefix added automatically.

    Examples:
        get_logger("mcp.flights")    → mcp.log
        get_logger("llm.waterfall")  → llm.log
        get_logger("guardrails")     → guardrails.log
    """
    full = f"voyageai.{name}" if not name.startswith("voyageai") else name
    return logging.getLogger(full)


setup_logging = init_logging
