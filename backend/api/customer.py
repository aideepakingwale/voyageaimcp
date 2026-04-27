"""Customer profile endpoints."""
import sqlite3
import os
from flask import Blueprint, jsonify
from mcp_servers import MCP_REGISTRY

bp = Blueprint("customer", __name__)

DB_PATH = os.path.join(os.path.dirname(__file__), "../data/voyageai.db")


@bp.route("/customers", methods=["GET"])
def list_customers():
    """Return all demo customers for the UI dropdown."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("""
            SELECT c.id, c.name, c.email, c.travel_style,
                   la.tier, la.member_id, la.points_balance
            FROM customers c
            LEFT JOIN loyalty_accounts la ON la.customer_id = c.id
            ORDER BY CASE la.tier
                WHEN 'Platinum' THEN 1 WHEN 'Gold' THEN 2
                WHEN 'Silver' THEN 3 ELSE 4 END
        """).fetchall()
        return jsonify({"customers": [dict(r) for r in rows]})
    finally:
        conn.close()


@bp.route("/customer/<lookup>", methods=["GET"])
def get_customer(lookup: str):
    """Look up customer by ID, email, or partial name."""
    srv = MCP_REGISTRY.get("customer")
    if not srv:
        return jsonify({"error": "Customer MCP unavailable"}), 503

    result = srv.call({"customer_id": lookup, "email": lookup, "name": lookup})
    inner  = result.get("data") or {}

    if not inner.get("profile"):
        return jsonify({"found": False, "message": f"No customer found: {lookup}"}), 404

    return jsonify({"found": True, **inner})
