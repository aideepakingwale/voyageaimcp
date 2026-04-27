"""
VoyageAI Server Entry Point
Run:  python run.py
Open: http://127.0.0.1:5000
"""
import os
import sys

# ── Logging MUST be set up before any other import ────────────
from core.logging_config import setup_logging
setup_logging()

# ── Now safe to import everything else ────────────────────────
from flask import send_from_directory
from app import create_app
from core.logging_config import get_logger

log      = get_logger("app")
app      = create_app()
FRONTEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))


@app.route("/")
def root():
    return send_from_directory(FRONTEND, "login.html")

@app.route("/login")
def login_page():
    return send_from_directory(FRONTEND, "login.html")

@app.route("/app")
def app_page():
    return send_from_directory(FRONTEND, "index.html")

@app.route("/logs")
def logs_page():
    return send_from_directory(FRONTEND, "logs.html")

@app.route("/<path:filename>")
def static_files(filename):
    return send_from_directory(FRONTEND, filename)


if __name__ == "__main__":
    log.info("VoyageAI server starting",
             extra={"frontend": FRONTEND, "port": 5000, "debug": True})
    print(f"\n  ✓ Frontend: {FRONTEND}")
    print(f"  ✓ Open:     http://127.0.0.1:5000")
    print(f"  ✓ Logs:     {os.path.abspath('logs/')}\n")
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=True)
