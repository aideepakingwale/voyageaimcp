"""Smart ancillary recommendation endpoints."""
from flask import Blueprint, request, jsonify
from mcp_servers import MCP_REGISTRY

bp = Blueprint("ancillaries", __name__)


@bp.route("/ancillaries", methods=["POST"])
def smart_ancillaries():
    """
    Get AI-recommended ancillaries based on trip context.
    Body: { city_code, departure_date, arrival_time, guests, children,
            trip_type, interests, loyalty_tier, nights, hotel_stars,
            budget_gbp, trip_cost_so_far }
    """
    srv = MCP_REGISTRY.get("ancillaries")
    if not srv:
        return jsonify({"error": "Ancillary MCP unavailable"}), 503

    return jsonify(srv.call(request.get_json(silent=True) or {}))
