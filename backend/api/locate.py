"""
Location & IATA Resolution Endpoints

GET  /api/locate           — Detect origin airport from client IP
POST /api/locate/resolve   — Resolve any city/text to IATA code (AI-powered)
GET  /api/locate/airports  — Search airports by name/city for autocomplete
"""
import os
from flask import Blueprint, request, jsonify
from core.geo_location import (
    locate_ip, city_to_iata, iata_for_location,
    CITY_TO_AIRPORT, COUNTRY_TO_AIRPORT,
)
from core.logging_config import get_logger

bp  = Blueprint("locate", __name__)
log = get_logger("app")


@bp.route("/locate", methods=["GET"])
def detect_origin():
    """
    Detect the caller's origin airport from their IP address.
    Returns the detected city, country, and nearest IATA code.
    Falls back gracefully when IP is private or geolocation fails.
    """
    # Get real client IP (handles proxies / nginx)
    ip = (request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
          or request.headers.get("X-Real-IP", "")
          or request.remote_addr
          or "")

    log.info("Location detect", extra={"ip": ip})

    geo = locate_ip(ip)

    if geo:
        return jsonify({
            "detected":     True,
            "city":         geo["city"],
            "country":      geo["country"],
            "country_code": geo["country_code"],
            "iata":         geo["iata"],
            "timezone":     geo.get("timezone",""),
            "display":      f"{geo['city']}, {geo['country']} ({geo['iata']})",
            "source":       "ip_geolocation",
        })

    # Private IP (local dev) or geolocation failed
    return jsonify({
        "detected":  False,
        "iata":      None,
        "message":   "Could not detect location automatically. Please enter your departure city.",
        "source":    "unavailable",
    })


@bp.route("/locate/resolve", methods=["POST"])
def resolve_location():
    """
    Resolve a free-text location to an IATA airport code.
    Tries local lookup first, then LLM if unknown.

    Body: { "text": "Manchester" | "Near Birmingham" | "MAN" | "UK Midlands" }
    Returns: { "iata": "MAN", "city": "Manchester", "confidence": 0.99 }
    """
    body = request.get_json(silent=True) or {}
    text = (body.get("text") or "").strip()

    if not text:
        return jsonify({"error": "text is required"}), 400

    # 1. Already an IATA code (3 uppercase letters)
    if len(text) == 3 and text.upper().isalpha():
        iata = text.upper()
        return jsonify({
            "iata":       iata,
            "city":       iata,
            "confidence": 0.99,
            "source":     "direct_iata",
        })

    # 2. Local dictionary lookup
    found = city_to_iata(text)
    if found:
        return jsonify({
            "iata":       found,
            "city":       text.title(),
            "confidence": 0.98,
            "source":     "local_lookup",
        })

    # 3. Partial match — find closest entry
    text_l = text.lower()
    partial = next(
        (code for city, code in CITY_TO_AIRPORT.items() if text_l in city or city in text_l),
        None,
    )
    if partial:
        return jsonify({
            "iata":       partial,
            "city":       text.title(),
            "confidence": 0.88,
            "source":     "partial_match",
        })

    # 4. Country lookup
    country_iata = COUNTRY_TO_AIRPORT.get(text_l)
    if country_iata:
        return jsonify({
            "iata":       country_iata,
            "city":       text.title(),
            "confidence": 0.85,
            "source":     "country_lookup",
        })

    # 5. Amadeus Airport Search for unusual city names
    try:
        from mcp_servers.iata_resolver import resolve_to_iata
        result = resolve_to_iata(text)
        if result.get("iata"):
            return jsonify({**result, "source": result.get("source","amadeus")})
    except Exception:
        pass

    # 6. LLM-powered resolution as last resort
    llm_result = _llm_resolve(text)
    if llm_result:
        return jsonify({**llm_result, "source": "llm_resolved"})

    return jsonify({
        "iata":       None,
        "city":       text,
        "confidence": 0.0,
        "message":    f"Could not find airport for '{text}'. Try entering a major nearby city.",
        "source":     "not_found",
    }), 404


@bp.route("/locate/airports", methods=["GET"])
def search_airports():
    """
    Autocomplete airport search — tries Amadeus first, then local dict.
    Query param: q=man  →  [{"city":"Manchester","iata":"MAN","country":"UK"}, ...]
    """
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return jsonify({"results": []})
    try:
        from mcp_servers.iata_resolver import search_airports as _search
        results = _search(q, limit=10)
        return jsonify({"results": results})
    except Exception as e:
        log.debug("Airport search error: %s", e)
        # Fallback to local dict
        q_l = q.lower()
        results = [
            {"city": city.title(), "iata": code,
             "display": f"{city.title()} ({code})", "country": ""}
            for city, code in CITY_TO_AIRPORT.items()
            if q_l in city
        ][:10]
        return jsonify({"results": results})


def _llm_resolve(text: str) -> dict | None:
    """Ask the LLM to identify the IATA code for an unusual location."""
    try:
        from llm import get_waterfall
        wf   = get_waterfall()
        resp = wf.complete(
            system=(
                "You are an airport code expert. Given a city, region, or location name, "
                "return ONLY a JSON object with the nearest major international airport. "
                'Format: {"iata":"XXX","city":"City Name","country":"Country"} '
                "Return the JSON object and nothing else. "
                "If you cannot identify it, return {\"iata\":null}."
            ),
            user=f"What is the IATA airport code for: {text}",
            max_tokens=60,
            temperature=0.0,
        )
        if resp.success:
            import json
            result = json.loads(resp.text)
            if result.get("iata"):
                return {
                    "iata":       result["iata"].upper(),
                    "city":       result.get("city", text.title()),
                    "country":    result.get("country",""),
                    "confidence": 0.80,
                }
    except Exception as e:
        log.debug("LLM location resolve failed: %s", e)
    return None
