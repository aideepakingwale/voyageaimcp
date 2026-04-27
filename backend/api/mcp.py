"""Direct MCP server access endpoints — for testing and debugging."""
from flask import Blueprint, request, jsonify
from mcp_servers import MCP_REGISTRY

bp = Blueprint("mcp", __name__)


@bp.route("/mcp", methods=["GET"])
def list_mcp():
    """List all registered MCP servers and their current status."""
    return jsonify({
        "servers": {
            name: {
                "class":      srv.__class__.__name__,
                "latency_ms": round(srv.latency, 1),
            }
            for name, srv in MCP_REGISTRY.items()
        },
        "count": len(MCP_REGISTRY),
    })


@bp.route("/mcp/<server_name>", methods=["POST"])
def call_mcp(server_name: str):
    """
    Call a specific MCP server directly.
    Useful for debugging, testing, and the VoyageAI demo UI.
    """
    srv = MCP_REGISTRY.get(server_name)
    if not srv:
        return jsonify({
            "error":     f"Unknown MCP server: {server_name}",
            "available": list(MCP_REGISTRY.keys()),
        }), 404

    params = request.get_json(silent=True) or {}
    return jsonify(srv.call(params))
