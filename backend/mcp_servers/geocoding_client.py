"""
VoyageAI Geocoding Client
==========================
Converts any place name → (lat, lon) by querying real external APIs.
No hardcoded coordinates anywhere.

Provider waterfall (tried in order until one succeeds):

  1. Amadeus Location Search
     GET /v1/reference-data/locations?keyword=&subType=CITY,AIRPORT
     — Uses the existing Amadeus credentials. Excellent for cities,
       airports and major destinations.

  2. OpenStreetMap Nominatim
     GET https://nominatim.openstreetmap.org/search?q=&format=json
     — Free, no API key, global coverage including heritage sites,
       temples, national parks, villages. Best general-purpose geocoder.

  3. Photon (Komoot) — OSM-based, no rate limit for reasonable usage
     GET https://photon.komoot.io/api/?q=&limit=1
     — Alternative OSM geocoder, different result set.

  4. LLM (Groq / Gemini)
     — Ask the language model for coordinates. Handles unusual spellings,
       local language names, and newly built destinations.

  5. Hard fail → returns None (caller must handle gracefully)

Configuration (optional, in .env):
  GEOCODING_PROVIDER=auto        # auto | nominatim | amadeus | llm
  GEOCODING_USER_AGENT=VoyageAI  # Nominatim User-Agent (required by OSM policy)

All results are TTL-cached in memory (24 hours) to avoid hammering APIs.
"""
import os
import time
import logging
from typing import Optional

log = logging.getLogger("voyageai.mcp")

# ── Cache (in-memory, 24h TTL) ────────────────────────────────────────────────
_GEO_CACHE: dict[str, tuple[float, Optional[tuple[float, float, str]]]] = {}
_GEO_TTL   = 86_400  # 24 hours

_USER_AGENT = os.getenv("GEOCODING_USER_AGENT", "VoyageAI-TravelAssistant/1.0")


# ── Public API ────────────────────────────────────────────────────────────────

def geocode(place: str, country_hint: str = "") -> Optional[tuple[float, float, str]]:
    """
    Convert a place name to (lat, lon, source_provider).
    Returns None if all providers fail.

    Args:
        place:        Any place name — city, village, temple, national park, etc.
        country_hint: Optional ISO-2 country code to narrow results (e.g. "IN" for India)
    """
    key = f"{place.lower().strip()}|{country_hint.upper()}"
    if key in _GEO_CACHE:
        ts, cached = _GEO_CACHE[key]
        if time.time() - ts < _GEO_TTL:
            return cached

    result = _resolve(place, country_hint)
    _GEO_CACHE[key] = (time.time(), result)
    if result:
        log.info("Geocoded '%s' → (%.4f, %.4f) via %s", place, result[0], result[1], result[2])
    else:
        log.warning("Geocoding failed for '%s'", place)
    return result


def geocode_lat_lon(place: str, country_hint: str = "") -> Optional[tuple[float, float]]:
    """Convenience wrapper — returns (lat, lon) or None."""
    r = geocode(place, country_hint)
    return (r[0], r[1]) if r else None


def geocoding_status() -> dict:
    """Return which providers are configured and available."""
    from mcp_servers.amadeus_client import amadeus
    return {
        "amadeus":   {"available": amadeus.configured, "type": "api_key"},
        "nominatim": {"available": True, "type": "free_no_key"},
        "photon":    {"available": True, "type": "free_no_key"},
        "llm":       {"available": True, "type": "uses_llm_waterfall"},
        "cache_size": len(_GEO_CACHE),
    }


# ── Resolution chain ──────────────────────────────────────────────────────────

def _resolve(place: str, country_hint: str) -> Optional[tuple[float, float, str]]:
    q = place.strip()

    # ── Provider 1: Amadeus Location Search ──────────────────────────────────
    result = _amadeus_geocode(q, country_hint)
    if result:
        return result

    # ── Provider 2: OpenStreetMap Nominatim ──────────────────────────────────
    result = _nominatim_geocode(q, country_hint)
    if result:
        return result

    # ── Provider 3: Photon (Komoot) ───────────────────────────────────────────
    result = _photon_geocode(q, country_hint)
    if result:
        return result

    # ── Provider 4: LLM ───────────────────────────────────────────────────────
    result = _llm_geocode(q)
    if result:
        return result

    return None


# ── Provider implementations ──────────────────────────────────────────────────

def _amadeus_geocode(place: str, country_hint: str) -> Optional[tuple[float, float, str]]:
    """
    Amadeus Location Search API.
    Endpoint: GET /v1/reference-data/locations
    Docs: https://developers.amadeus.com/self-service/category/destination-experiences/
          api-doc/points-of-interest/api-reference
    Returns cities, airports, and major places with lat/lon.
    """
    try:
        from mcp_servers.amadeus_client import amadeus
        if not amadeus.configured:
            return None
        coords = amadeus.geocode_place(place)
        if coords:
            return (coords[0], coords[1], "amadeus")
    except Exception as e:
        log.debug("Amadeus geocode error for '%s': %s", place, e)
    return None


def _nominatim_geocode(place: str, country_hint: str) -> Optional[tuple[float, float, str]]:
    """
    OpenStreetMap Nominatim geocoding API.
    Endpoint: GET https://nominatim.openstreetmap.org/search
    Docs: https://nominatim.org/release-docs/develop/api/Search/
    Free, no API key, global coverage — temples, heritage sites, parks.
    OSM policy: must include User-Agent, max 1 req/sec.
    """
    try:
        from mcp_servers.http_client import get as http_get
        params: dict = {
            "q":              place,
            "format":         "jsonv2",
            "limit":          5,
            "addressdetails": 0,
            "extratags":      0,
        }
        if country_hint:
            params["countrycodes"] = country_hint.lower()

        r = http_get(
            "https://nominatim.openstreetmap.org/search",
            params=params,
            headers={"User-Agent": _USER_AGENT, "Accept-Language": "en"},
            timeout=8,
        )
        if not r.ok:
            log.debug("Nominatim %s: %s", r.status_code, r.text[:100])
            return None

        items = r.json()
        if not items:
            # Try without country filter
            if country_hint:
                return _nominatim_geocode(place, "")
            return None

        # Prefer important types: place, tourism, historic, natural
        PREFERRED = {"tourism", "historic", "natural", "place", "boundary",
                     "amenity", "leisure", "landuse"}
        ranked = sorted(
            items,
            key=lambda x: (
                x.get("category","") in PREFERRED,
                float(x.get("importance", 0)),
            ),
            reverse=True,
        )
        best = ranked[0]
        lat  = float(best["lat"])
        lon  = float(best["lon"])
        log.debug("Nominatim '%s' → (%s, %s) [%s]", place, lat, lon,
                  best.get("display_name","")[:60])
        return lat, lon, "nominatim"

    except Exception as e:
        log.debug("Nominatim error for '%s': %s", place, e)
    return None


def _photon_geocode(place: str, country_hint: str) -> Optional[tuple[float, float, str]]:
    """
    Photon geocoding API (Komoot, based on OpenStreetMap).
    Endpoint: GET https://photon.komoot.io/api/
    Docs: https://photon.komoot.io/
    Free, no key, good alternative to Nominatim.
    Returns GeoJSON FeatureCollection.
    """
    try:
        from mcp_servers.http_client import get as http_get
        params: dict = {"q": place, "limit": 3, "lang": "en"}
        if country_hint:
            # Photon uses bbox or language but not direct country filter
            # Append country to query for better results
            params["q"] = f"{place}, {country_hint}"

        r = http_get(
            "https://photon.komoot.io/api/",
            params=params,
            headers={"User-Agent": _USER_AGENT},
            timeout=8,
        )
        if not r.ok:
            return None

        features = r.json().get("features", [])
        if not features:
            return None

        coords = features[0].get("geometry", {}).get("coordinates", [])
        if len(coords) >= 2:
            lon, lat = float(coords[0]), float(coords[1])  # GeoJSON is lon,lat
            log.debug("Photon '%s' → (%s, %s)", place, lat, lon)
            return lat, lon, "photon"
    except Exception as e:
        log.debug("Photon error for '%s': %s", place, e)
    return None


def _llm_geocode(place: str) -> Optional[tuple[float, float, str]]:
    """
    Ask the LLM for coordinates as a last resort.
    Only tries one provider (groq/gemini) to keep latency low.
    """
    try:
        from llm.waterfall import get_waterfall
        from config import Config
        wf = get_waterfall()
        system = (
            'You are a geocoding assistant. '
            'Return ONLY a JSON object with two keys: {"lat": float, "lon": float}. '
            'No text, no markdown, no explanation.'
        )
        user = f'What are the WGS84 latitude and longitude coordinates of: "{place}"?'

        for pname in getattr(Config, "LLM_WATERFALL", ["groq", "gemini", "anthropic"]):
            if pname == "template":
                continue
            provider = getattr(wf, "providers", {}).get(pname)
            if not provider or not provider.is_available():
                continue
            try:
                resp = provider.complete(system, user, max_tokens=60, temperature=0.0)
                if resp.success and resp.text:
                    import json, re
                    m = re.search(r"\{[^}]+\}", resp.text)
                    if m:
                        d    = json.loads(m.group(0))
                        lat  = float(d.get("lat",  d.get("latitude",  0)))
                        lon  = float(d.get("lon",  d.get("longitude", 0)))
                        if -90 <= lat <= 90 and -180 <= lon <= 180 and (lat or lon):
                            log.info("LLM geocode '%s' → (%.4f, %.4f)", place, lat, lon)
                            return lat, lon, "llm"
            except Exception as e:
                log.debug("LLM provider %s geocode error: %s", pname, e)
            break   # Only try one LLM provider for geocoding
    except Exception as e:
        log.debug("LLM geocode error: %s", e)
    return None
