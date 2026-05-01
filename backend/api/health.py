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


@bp.route("/reference", methods=["GET"])
def reference_stats():
    """Inspect the startup reference cache."""
    try:
        from core.reference_cache import ref
        q    = request.args.get("q","").strip().upper()
        stats = ref.stats()
        if q:
            return jsonify({
                "query":      q,
                "is_airport": ref.is_airport(q),
                "is_currency":ref.is_currency(q),
                "is_country_code": ref.is_country_code(q),
                "is_non_airport":  ref.is_non_airport(q),
                "should_validate_as_iata": ref.should_validate_as_iata(q),
                "airport":    ref.airport(q),
                "currency":   ref.currency(q),
                "country":    ref.country(q),
                "cache_stats":stats,
            })
        return jsonify(stats)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/geocode", methods=["GET"])
def geocode_test():
    """
    Test the geocoding chain interactively.
    GET /api/geocode?q=Pushkar&country=IN
    Returns (lat, lon, provider) for any place.
    """
    place   = request.args.get("q", "").strip()
    country = request.args.get("country", "").strip().upper()
    if not place:
        return jsonify({"error": "q (place name) is required"}), 400
    from mcp_servers.geocoding_client import geocode, geocoding_status
    result  = geocode(place, country)
    if result:
        lat, lon, source = result
        # Also find nearest airport
        from reasoning.nearest_airport import find_nearest_airport
        airport = find_nearest_airport(place, country_hint=country)
        return jsonify({
            "place":     place,
            "lat":       lat,
            "lon":       lon,
            "geo_source":source,
            "nearest_airport": airport.to_dict() if airport else None,
            "providers": geocoding_status(),
        })
    return jsonify({
        "place":   place,
        "error":   "Could not geocode this place",
        "providers": geocoding_status(),
    }), 404
