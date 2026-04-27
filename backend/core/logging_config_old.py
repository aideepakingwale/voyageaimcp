"""
VoyageAI Logging Configuration
================================
Separate rotating log files per subsystem.

  logs/
  ├── app.log          Flask requests, sessions, auth events
  ├── llm.log          LLM waterfall calls (provider, model, latency, tokens, cost)
  ├── mcp.log          Downstream MCP calls (live vs fallback, latency, confidence)
  ├── guardrails.log   Guardrail decisions (layer, pass/fail, reason)
  ├── auth.log         Login/logout events
  ├── errors.log       All ERROR+ from every module
  └── debug.log        Full verbose (set LOG_LEVEL=DEBUG in .env)

Each file rotates at 5 MB, keeps 5 backups.
Format: JSON per line — easy to grep, parse, or forward to ELK/Splunk.

Usage anywhere in the codebase:
    from core.logging_config import get_logger
    log = get_logger("mcp.flights")
    log.info("Search", extra={"origin":"LHR", "results":5, "source":"live", "ms":230})
"""
import os, sys, json, logging, logging.handlers
from datetime import datetime, timezone
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent
LOG_DIR       = _BACKEND_DIR.parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

_DEBUG_MODE = os.getenv("LOG_LEVEL","INFO").upper() == "DEBUG"
_INITIALISED = False


# ── Formatters ────────────────────────────────────────────────

class JsonFormatter(logging.Formatter):
    """One JSON object per line — grep-friendly."""
    _SKIP = {"name","msg","args","levelname","levelno","pathname","filename","module",
              "exc_info","exc_text","stack_info","lineno","funcName","created","msecs",
              "relativeCreated","thread","threadName","processName","process",
              "message","taskName"}

    def format(self, record):
        obj = {
            "ts":     datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]+"Z",
            "level":  record.levelname,
            "logger": record.name,
            "msg":    record.getMessage(),
        }
        ctx = {k: v for k,v in record.__dict__.items() if k not in self._SKIP}
        if ctx:
            obj["ctx"] = ctx
        if record.exc_info:
            obj["exc"] = self.formatException(record.exc_info)
        return json.dumps(obj, default=str)


class ConsoleFormatter(logging.Formatter):
    """Coloured human-readable output for the terminal."""
    C = {"DEBUG":"\033[36m","INFO":"\033[32m","WARNING":"\033[33m",
         "ERROR":"\033[31m","CRITICAL":"\033[35m"}
    R = "\033[0m"
    _SKIP = {"name","msg","args","levelname","levelno","pathname","filename","module",
              "exc_info","exc_text","stack_info","lineno","funcName","created","msecs",
              "relativeCreated","thread","threadName","processName","process",
              "message","taskName"}

    def format(self, record):
        c   = self.C.get(record.levelname,"")
        ts  = datetime.now().strftime("%H:%M:%S")
        msg = record.getMessage()
        ctx = {k:v for k,v in record.__dict__.items() if k not in self._SKIP}
        suf = f"  {json.dumps(ctx, default=str)}" if ctx else ""
        out = f"{ts} {c}{record.levelname:<8}{self.R} [{record.name}] {msg}{suf}"
        if record.exc_info:
            out += "\n" + self.formatException(record.exc_info)
        return out


# ── Handler factory ───────────────────────────────────────────

def _file_handler(name, level=logging.DEBUG, mb=5, backups=5):
    h = logging.handlers.RotatingFileHandler(
        LOG_DIR / name, maxBytes=mb*1024*1024,
        backupCount=backups, encoding="utf-8"
    )
    h.setLevel(level)
    h.setFormatter(JsonFormatter())
    return h


def _console():
    h = logging.StreamHandler(sys.stdout)
    h.setLevel(logging.DEBUG if _DEBUG_MODE else logging.INFO)
    h.setFormatter(ConsoleFormatter())
    return h


# ── Subsystem log files ───────────────────────────────────────

_SUBSYSTEMS = {
    "voyageai.app":        "app.log",
    "voyageai.llm":        "llm.log",
    "voyageai.mcp":        "mcp.log",
    "voyageai.guardrails": "guardrails.log",
    "voyageai.rag":        "rag.log",
    "voyageai.auth":       "auth.log",
    "voyageai.reasoning":  "app.log",   # reasoning → app.log
}


def init_logging():
    """Call once at startup (app.py). Safe to call multiple times."""
    global _INITIALISED
    if _INITIALISED:
        return
    _INITIALISED = True

    # Shared error file — catches ERROR+ from everything
    err_handler = _file_handler("errors.log", level=logging.ERROR)

    # Root: WARNING+ only (third-party libs)
    root = logging.getLogger()
    root.setLevel(logging.WARNING)
    root.addHandler(err_handler)

    # Per-subsystem loggers
    for prefix, filename in _SUBSYSTEMS.items():
        lg = logging.getLogger(prefix)
        lg.setLevel(logging.DEBUG)
        lg.propagate = False
        lg.addHandler(_file_handler(filename))
        lg.addHandler(_console())
        lg.addHandler(err_handler)   # errors always mirror to errors.log

    # Optional full-verbose debug log
    if _DEBUG_MODE:
        dbg = logging.getLogger("voyageai")
        dbg.addHandler(_file_handler("debug.log", level=logging.DEBUG))

    # Werkzeug → app.log (not just stdout)
    wz = logging.getLogger("werkzeug")
    wz.setLevel(logging.INFO)
    wz.propagate = False
    wz.addHandler(_file_handler("app.log", level=logging.INFO))

    # Silence noisy third-party libs
    for lib in ("urllib3","requests","httpcore","httpx","google",
                "anthropic._base_client","groq._base_client"):
        logging.getLogger(lib).setLevel(logging.ERROR)

    print(f"\n  ✓ Logging → {LOG_DIR}")
    lvl = "DEBUG" if _DEBUG_MODE else "INFO"
    print(f"    Level:  {lvl}  |  Files: app · llm · mcp · guardrails · auth · errors"
          + (" · debug" if _DEBUG_MODE else ""))


def get_logger(name: str) -> logging.Logger:
    """
    Get a named logger.  name is appended to 'voyageai.' automatically.
    Examples:
        get_logger("mcp.flights")   →  voyageai.mcp.flights
        get_logger("llm.groq")      →  voyageai.llm.groq
        get_logger("app")           →  voyageai.app
    """
    full = f"voyageai.{name}" if not name.startswith("voyageai") else name
    return logging.getLogger(full)
