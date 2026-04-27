"""
Auth endpoints — login, logout, current user.
Demo auth: email + member_id as password (no real crypto needed for PoC).
Each login creates a brand-new session — full isolation guaranteed.
"""
import sqlite3
import os
from flask import Blueprint, jsonify, request, session
from rag.memory_store import memory_store
from core.logging_config  import get_logger
from core.request_context import get_request_id

_log = get_logger("auth")

bp      = Blueprint("auth", __name__)
DB_PATH = os.path.join(os.path.dirname(__file__), "../data/voyageai.db")

from core.logging_config import get_logger
_log = get_logger("auth")

# In-memory active sessions: session_token → customer_id
_active_logins: dict[str, str] = {}


def _get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@bp.route("/auth/login", methods=["POST"])
def login():
    """
    Authenticate a customer.
    Body: { email, member_id }
    Returns: { token, customer_id, name, tier, ... }

    Demo credentials (email / member_id):
      sarah.mitchell@email.com  / VGI-GOLD-1001
      james.okafor@corp.com     / VGI-PLAT-2001
      priya.sharma@gmail.com    / VGI-SILV-3001
      tom.bradley@email.com     / VGI-BLUE-4001
      emma.clarke@email.com     / VGI-GOLD-5001
    """
    body      = request.get_json(silent=True) or {}
    email     = (body.get("email")     or "").strip().lower()
    member_id = (body.get("member_id") or "").strip().upper()

    if not email or not member_id:
        return jsonify({"error": "Email and Member ID are required"}), 400

    conn = _get_db()
    try:
        row = conn.execute("""
            SELECT c.id, c.name, c.email, c.travel_style,
                   c.adults_in_family, c.children_in_family,
                   la.tier, la.member_id, la.points_balance,
                   la.total_nights_ytd, la.total_flights_ytd,
                   la.member_since, la.tier_expiry
            FROM customers c
            JOIN loyalty_accounts la ON la.customer_id = c.id
            WHERE LOWER(c.email) = ? AND la.member_id = ?
        """, (email, member_id)).fetchone()

        if not row:
            _log.warning("LOGIN FAILED",
                         extra={"request_id": get_request_id(),
                                "email": email[:20],
                                "member_id": member_id})
            return jsonify({
                "error": "Invalid email or Member ID. Please check your credentials."
            }), 401

        row = dict(row)

        # Create a brand-new RAG session for this login
        sid = memory_store.create_session()

        # Store login mapping
        import uuid
        token = str(uuid.uuid4())[:16]
        _active_logins[token] = row["id"]

        # Seed session with customer context
        memory_store.store_entity(sid, "customer_id",   row["id"],    1.0)
        memory_store.store_entity(sid, "customer_name", row["name"],  1.0)
        memory_store.store_entity(sid, "loyalty_tier",  row["tier"],  1.0)

        _log.info("LOGIN SUCCESS",
                     extra={"request_id": get_request_id(),
                            "customer_id": row["id"],
                            "customer_name": row["name"],
                            "tier":        row["tier"],
                            "member_id":   row["member_id"]})
        _log.info("Login success", extra={
            "customer_id": row["id"],
            "customer_name": row["name"],
            "tier":        row["tier"],
            "member_id":   row["member_id"],
            "ip":          request.remote_addr,
        })
        return jsonify({
            "token":       token,
            "session_id":  sid,
            "customer_id": row["id"],
            "customer_name": row["name"],
            "email":       row["email"],
            "tier":        row["tier"],
            "member_id":   row["member_id"],
            "points":      row["points_balance"],
            "nights_ytd":  row["total_nights_ytd"],
            "flights_ytd": row["total_flights_ytd"],
            "member_since":row["member_since"],
            "tier_expiry": row["tier_expiry"],
            "travel_style":row["travel_style"],
            "adults":      row["adults_in_family"],
            "children":    row["children_in_family"],
        })

    finally:
        conn.close()


@bp.route("/auth/logout", methods=["POST"])
def logout():
    """
    Log out — destroys the session and clears auth token.
    Body: { token, session_id }
    """
    body       = request.get_json(silent=True) or {}
    token      = body.get("token", "")
    session_id = body.get("session_id", "")

    _active_logins.pop(token, None)

    # Clear the RAG session
    s = memory_store.get_session(session_id)
    if s:
        s["entities"]  = {}
        s["history"]   = []
        s["confirmed"] = {}

    _log.info("LOGOUT", extra={"request_id": get_request_id(), "token_prefix": token[:6]})
    _log.info("Logout", extra={"token_prefix": token[:4] if token else ""})
    return jsonify({"logged_out": True})


@bp.route("/auth/me", methods=["GET"])
def me():
    """Return current user info from token (for page refresh persistence)."""
    token = request.headers.get("X-Auth-Token", "")
    cid   = _active_logins.get(token)
    if not cid:
        return jsonify({"authenticated": False}), 401

    conn = _get_db()
    try:
        row = conn.execute("""
            SELECT c.id, c.name, c.email, c.travel_style,
                   la.tier, la.member_id, la.points_balance
            FROM customers c
            JOIN loyalty_accounts la ON la.customer_id = c.id
            WHERE c.id = ?
        """, (cid,)).fetchone()

        if not row:
            return jsonify({"authenticated": False}), 401

        return jsonify({"authenticated": True, **dict(row)})
    finally:
        conn.close()


@bp.route("/auth/demo-credentials", methods=["GET"])
def demo_credentials():
    """Return demo login credentials for the login screen hint."""
    conn = _get_db()
    try:
        rows = conn.execute("""
            SELECT c.name, c.email, c.travel_style,
                   la.tier, la.member_id
            FROM customers c
            JOIN loyalty_accounts la ON la.customer_id = c.id
            ORDER BY CASE la.tier
                WHEN 'Platinum' THEN 1 WHEN 'Gold' THEN 2
                WHEN 'Silver' THEN 3 ELSE 4 END
        """).fetchall()
        return jsonify({"credentials": [dict(r) for r in rows]})
    finally:
        conn.close()
