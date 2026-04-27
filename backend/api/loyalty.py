"""Loyalty program endpoints."""
from flask import Blueprint, request, jsonify
from mcp_servers import MCP_REGISTRY

bp = Blueprint("loyalty", __name__)


@bp.route("/loyalty/<customer_id>", methods=["POST"])
def loyalty_for_trip(customer_id: str):
    """
    Calculate loyalty impact for a proposed trip.
    Body: { trip_cost_gbp, nights, flights }
    """
    body = request.get_json(silent=True) or {}
    srv  = MCP_REGISTRY.get("loyalty")
    if not srv:
        return jsonify({"error": "Loyalty MCP unavailable"}), 503

    return jsonify(srv.call({
        "customer_id":   customer_id,
        "trip_cost_gbp": body.get("trip_cost_gbp", 0),
        "nights":        body.get("nights", 7),
        "flights":       body.get("flights", 1),
    }))
