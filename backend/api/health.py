"""Health and waterfall status endpoints."""
import time
from flask import Blueprint, jsonify
from config import Config

bp = Blueprint("health", __name__)


@bp.route("/health", methods=["GET"])
def health():
    """Server health check — returns LLM waterfall + MCP status."""
    from llm import get_waterfall
    from mcp_servers import MCP_REGISTRY

    return jsonify({
        "status":               "healthy",
        "version":              "3.0.0",
        "llm_waterfall":        get_waterfall().get_status(),
        "mcp_servers":          list(MCP_REGISTRY.keys()),
        "confidence_threshold": Config.CONFIDENCE_THRESHOLD,
        "gds_session_timeout":  Config.GDS_SESSION_TIMEOUT,
        "timestamp":            time.time(),
    })


@bp.route("/waterfall", methods=["GET"])
def waterfall_status():
    """LLM provider waterfall stats — calls, success rate, latency, cost."""
    from llm import get_waterfall
    return jsonify(get_waterfall().get_status())
