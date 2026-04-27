"""
Log Viewer API
==============
Read-only endpoints for viewing and searching logs from the browser.
Only accessible in debug mode.

GET /api/logs                 — list all log files + sizes
GET /api/logs/<file>          — tail last N lines of a log file
GET /api/logs/<file>/search   — search for a term or request_id
"""
import os
import json
from pathlib import Path
from flask import Blueprint, jsonify, request, current_app

bp      = Blueprint("logs", __name__)
LOG_DIR = Path(os.getenv("VOYAGE_LOG_DIR",
               os.path.join(os.path.dirname(__file__), "..", "logs")))

ALLOWED_FILES = {
    "app", "api", "mcp", "llm", "guardrails", "auth", "errors"
}


@bp.route("/logs", methods=["GET"])
def list_logs():
    """List all log files with sizes and last-modified times."""
    if not LOG_DIR.exists():
        return jsonify({"files": [], "log_dir": str(LOG_DIR),
                        "message": "No logs yet — make some API calls first"})

    files = []
    for f in sorted(LOG_DIR.glob("*.log")):
        stat = f.stat()
        files.append({
            "name":         f.name,
            "stem":         f.stem,
            "size_bytes":   stat.st_size,
            "size_human":   _human_size(stat.st_size),
            "modified":     stat.st_mtime,
            "lines":        _count_lines(f),
        })
    return jsonify({
        "log_dir": str(LOG_DIR),
        "files":   files,
        "count":   len(files),
    })


@bp.route("/logs/<stem>", methods=["GET"])
def tail_log(stem: str):
    """
    Tail the last N lines of a log file.
    Query params:
      n=100      — number of lines (default 100, max 1000)
      format=raw — return raw text instead of parsed JSON lines
    """
    if stem not in ALLOWED_FILES:
        return jsonify({"error": f"Unknown log: {stem}",
                        "allowed": list(ALLOWED_FILES)}), 404

    path = LOG_DIR / f"{stem}.log"
    if not path.exists():
        return jsonify({"lines": [], "message": f"{stem}.log not found yet"})

    n      = min(int(request.args.get("n", 100)), 1000)
    fmt    = request.args.get("format", "json")
    raw    = _tail(path, n)

    if fmt == "raw":
        return "\n".join(raw), 200, {"Content-Type": "text/plain; charset=utf-8"}

    # Parse JSON lines
    parsed = []
    for line in raw:
        line = line.strip()
        if not line:
            continue
        try:
            parsed.append(json.loads(line))
        except json.JSONDecodeError:
            parsed.append({"raw": line})

    return jsonify({
        "file":  f"{stem}.log",
        "lines": parsed,
        "count": len(parsed),
        "log_dir": str(LOG_DIR),
    })


@bp.route("/logs/<stem>/search", methods=["GET"])
def search_log(stem: str):
    """
    Search a log file for a term or request_id.
    Query params:
      q=<term>          — search term (case-insensitive)
      request_id=<id>   — filter by specific request ID
      level=ERROR       — filter by log level
      n=200             — max results
    """
    if stem not in ALLOWED_FILES:
        return jsonify({"error": f"Unknown log: {stem}"}), 404

    path = LOG_DIR / f"{stem}.log"
    if not path.exists():
        return jsonify({"results": [], "message": "Log file not found"})

    query      = (request.args.get("q") or "").lower()
    request_id = request.args.get("request_id", "")
    level_filt = (request.args.get("level") or "").upper()
    max_n      = min(int(request.args.get("n", 200)), 2000)

    results = []
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                # Quick string filter before JSON parse
                if query and query not in line.lower():
                    continue
                if request_id and request_id not in line:
                    continue
                try:
                    doc = json.loads(line)
                except json.JSONDecodeError:
                    doc = {"raw": line}

                if level_filt and doc.get("level","") != level_filt:
                    continue

                results.append(doc)
                if len(results) >= max_n:
                    break
    except OSError as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({
        "file":    f"{stem}.log",
        "query":   query or request_id or level_filt,
        "results": results,
        "count":   len(results),
    })


# ── Helpers ───────────────────────────────────────────────────

def _tail(path: Path, n: int) -> list[str]:
    """Efficient tail — reads only the last n lines."""
    with open(path, "rb") as fh:
        fh.seek(0, 2)
        size = fh.tell()
        if size == 0:
            return []
        block = min(size, 1024 * 64)   # read up to 64 KB
        fh.seek(max(0, size - block))
        data  = fh.read().decode("utf-8", errors="replace")
    lines = data.splitlines()
    return lines[-n:]


def _count_lines(path: Path) -> int:
    try:
        with open(path, "rb") as fh:
            return sum(1 for _ in fh)
    except OSError:
        return 0


def _human_size(n: int) -> str:
    for unit in ("B","KB","MB","GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"
