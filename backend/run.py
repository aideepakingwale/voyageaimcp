"""
VoyageAI Server — serves both API and frontend.
Run:  python run.py
Open: http://127.0.0.1:5000
"""
import os
from flask import send_from_directory
from app import create_app

app      = create_app()
FRONTEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))


@app.route("/")
def root():
    """Root redirects to login page."""
    return send_from_directory(FRONTEND, "login.html")


@app.route("/login")
def login_page():
    return send_from_directory(FRONTEND, "login.html")


@app.route("/app")
def app_page():
    return send_from_directory(FRONTEND, "index.html")


@app.route("/<path:filename>")
def static_files(filename):
    """Serve any frontend static file (JS, CSS, HTML)."""
    return send_from_directory(FRONTEND, filename)


if __name__ == "__main__":
    print(f"\n  ✓ Frontend: {FRONTEND}")
    print(f"  ✓ Open:     http://127.0.0.1:5000\n")
    app.run(host="0.0.0.0", port=5000, debug=True)
