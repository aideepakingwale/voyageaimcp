"""
VoyageAI Logging Configuration
Separate rotating log files per subsystem.

  logs/
  ├── app.log          Flask requests, sessions, auth events
  ├── llm.log          LLM waterfall calls (provider, latency, tokens, cost)
  ├── mcp.log          MCP server calls (live vs fallback, latency, confidence)
  ├── guardrails.log   Guardrail layer decisions
  ├── auth.log         Login / logout events
  ├── errors.log       ALL ERROR+ from every module
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

_DEBUG_MODE   = os.getenv("LOG_LEVEL","INFO").upper() == "DEBUG"
_done         = False
_lock         = threading.Lock()


# ── Formatters ────────────────────────────────────────────────

class JSONFormatter(logging.Formatter):
    _SKIP = {
        "name","msg","args","levelname","levelno","pathname","filename","module",
        "exc_info","exc_text","stack_info","lineno","funcName","created","msecs",
        "relativeCreated","thread","threadName","processName","process","message","taskName",
    }
    def format(self, r):
        obj = {
            "ts":     datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]+"Z",
            "level":  r.levelname,
            "logger": r.name,
            "msg":    r.getMessage(),
        }
        ctx = {k: v for k,v in r.__dict__.items() if k not in self._SKIP}
        if ctx:   obj["ctx"] = ctx
        if r.exc_info: obj["exc"] = self.formatException(r.exc_info)
        return json.dumps(obj, default=str)


class ConsoleFormatter(logging.Formatter):
    _C = {"DEBUG":"\033[36m","INFO":"\033[32m","WARNING":"\033[33m",
          "ERROR":"\033[31m","CRITICAL":"\033[35m"}
    _R = "\033[0m"
    _SKIP = {
        "name","msg","args","levelname","levelno","pathname","filename","module",
        "exc_info","exc_text","stack_info","lineno","funcName","created","msecs",
        "relativeCreated","thread","threadName","processName","process","message","taskName",
    }
    def format(self, r):
        c   = self._C.get(r.levelname,"")
        ts  = datetime.now().strftime("%H:%M:%S")
        ctx = {k:v for k,v in r.__dict__.items() if k not in self._SKIP}
        suf = f"  {json.dumps(ctx, default=str)}" if ctx else ""
        out = f"{ts} {c}{r.levelname:<8}{self._R} [{r.name}] {r.getMessage()}{suf}"
        if r.exc_info: out += "\n" + self.formatException(r.exc_info)
        return out


# ── Handler factories ─────────────────────────────────────────

def _rot_handler(filename, level=logging.DEBUG, mb=5, bk=5):
    h = logging.handlers.RotatingFileHandler(
        LOG_DIR / filename, maxBytes=mb*1024*1024,
        backupCount=bk, encoding="utf-8"
    )
    h.setLevel(level)
    h.setFormatter(JSONFormatter())
    return h


def _console_handler():
    h = logging.StreamHandler(sys.stdout)
    h.setLevel(logging.DEBUG if _DEBUG_MODE else logging.INFO)
    h.setFormatter(ConsoleFormatter())
    return h


# ── Subsystem → log file mapping ──────────────────────────────

_SUBSYSTEMS = {
    "voyageai.app":        "app.log",
    "voyageai.llm":        "llm.log",
    "voyageai.mcp":        "mcp.log",
    "voyageai.guardrails": "guardrails.log",
    "voyageai.rag":        "rag.log",
    "voyageai.auth":       "auth.log",
    "voyageai.reasoning":  "app.log",
}

# Logger constants (for import in other modules)
LOGGER_APP        = "voyageai.app"
LOGGER_LLM        = "voyageai.llm"
LOGGER_MCP        = "voyageai.mcp"
LOGGER_GUARDRAILS = "voyageai.guardrails"
LOGGER_API        = "voyageai.app"
LOGGER_AUTH       = "voyageai.auth"

MAX_BYTES    = 5 * 1024 * 1024
BACKUP_COUNT = 5


def init_logging() -> None:
    """Call once at app startup. Thread-safe, idempotent."""
    global _done
    with _lock:
        if _done:
            return
        _done = True

    err_handler = _rot_handler("errors.log", level=logging.ERROR)

    # Root — catch ERROR+ from everything (third-party libs included)
    root = logging.getLogger()
    root.setLevel(logging.WARNING)
    root.addHandler(err_handler)

    # Per-subsystem
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

    # Werkzeug → app.log
    wz = logging.getLogger("werkzeug")
    wz.setLevel(logging.INFO)
    wz.propagate = False
    wz.addHandler(_rot_handler("app.log", level=logging.INFO))
    wz.addHandler(_console_handler())

    # Silence noisy libs
    for lib in ("urllib3","requests","httpcore","httpx","google",
                "anthropic._base_client","groq._base_client","openai"):
        logging.getLogger(lib).setLevel(logging.ERROR)

    print(f"\n  ✓ Logs → {LOG_DIR}")
    print(f"    Files: app · llm · mcp · guardrails · auth · errors"
          + (" · debug" if _DEBUG_MODE else ""))


def get_logger(name: str) -> logging.Logger:
    """
    Get a named VoyageAI logger.
    'voyageai.' prefix is added automatically if not present.

    Examples:
        get_logger("mcp.flights")      → voyageai.mcp.flights   → mcp.log
        get_logger("llm.waterfall")    → voyageai.llm.waterfall  → llm.log
        get_logger("guardrails")       → voyageai.guardrails     → guardrails.log
        get_logger("auth")             → voyageai.auth           → auth.log
    """
    full = f"voyageai.{name}" if not name.startswith("voyageai") else name
    return logging.getLogger(full)


# Convenience alias
setup_logging = init_logging
