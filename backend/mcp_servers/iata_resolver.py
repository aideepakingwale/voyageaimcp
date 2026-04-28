"""
IATA Airport Code Resolver
PRIMARY:  Amadeus Airport & City Search API
          GET /v1/reference-data/locations?keyword=...&subType=AIRPORT,CITY
FALLBACK: Local 600+ city dictionary (core/geo_location.py)

Amadeus sandbox is FREE and returns real airport data.
"""
import os, logging
from .amadeus_client import amadeus
from .http_client    import get

log = logging.getLogger("voyageai.mcp")


def resolve_to_iata(text: str) -> dict:
    """
    Resolve any text (city name, partial name, country) to IATA code.
    Returns: { iata, name, city, country, type, source }
    """
    text = text.strip()
    if not text:
        return {"iata": None, "source": "empty"}

    # Already a 3-letter IATA code
    if len(text) == 3 and text.isalpha():
        return {"iata": text.upper(), "name": text.upper(), "source": "direct"}

    # Try Amadeus Airport & City Search
    if amadeus.configured:
        result = _amadeus_airport_search(text)
        if result:
            return {**result, "source": "amadeus_live"}

    # Try local geo_location dictionary
    try:
        from core.geo_location import city_to_iata, iata_for_location, CITY_TO_AIRPORT
        iata = city_to_iata(text) or iata_for_location(text)
        if iata:
            # Find city name
            city = next((c.title() for c,code in CITY_TO_AIRPORT.items()
                        if code == iata), text.title())
            return {"iata": iata, "name": f"{city} Airport", "city": city,
                    "country": "", "source": "local_dict"}
    except Exception:
        pass

    return {"iata": None, "source": "not_found",
            "message": f"Cannot find IATA code for '{text}'"}


def _amadeus_airport_search(keyword: str) -> dict | None:
    """Search Amadeus Airport & City Search API."""
    try:
        headers = amadeus._auth_header()
        if not headers:
            return None

        r = get(
            "https://test.api.amadeus.com/v1/reference-data/locations",
            params={
                "keyword":    keyword,
                "subType":    "AIRPORT,CITY",
                "view":       "LIGHT",
                "sort":       "analytics.travelers.score",
                "page[limit]":"5",
            },
            headers=headers,
            timeout=6,
        )
        if r and r.ok:
            data = r.json().get("data", [])
            # Prefer airports over cities
            airports = [d for d in data if d.get("subType") == "AIRPORT"]
            cities   = [d for d in data if d.get("subType") == "CITY"]
            best     = (airports or cities or data)
            if best:
                loc  = best[0]
                addr = loc.get("address", {})
                return {
                    "iata":    loc.get("iataCode"),
                    "name":    loc.get("name","").title(),
                    "city":    addr.get("cityName","").title(),
                    "country": addr.get("countryName","").title(),
                    "type":    loc.get("subType",""),
                }
    except Exception as e:
        log.debug("Amadeus airport search error: %s", e)
    return None


def search_airports(keyword: str, limit: int = 10) -> list[dict]:
    """
    Search airports by keyword — used for autocomplete.
    Returns list of { iata, name, city, country, display }
    """
    results = []

    # Try Amadeus first
    if amadeus.configured:
        try:
            headers = amadeus._auth_header()
            if headers:
                r = get(
                    "https://test.api.amadeus.com/v1/reference-data/locations",
                    params={
                        "keyword":    keyword,
                        "subType":    "AIRPORT,CITY",
                        "view":       "LIGHT",
                        "page[limit]":str(limit),
                    },
                    headers=headers,
                    timeout=6,
                )
                if r and r.ok:
                    for loc in r.json().get("data",[])[:limit]:
                        addr = loc.get("address",{})
                        iata = loc.get("iataCode","")
                        city = addr.get("cityName", loc.get("name","")).title()
                        country = addr.get("countryName","").title()
                        results.append({
                            "iata":    iata,
                            "name":    loc.get("name","").title(),
                            "city":    city,
                            "country": country,
                            "display": f"{city} ({iata}) — {country}",
                            "source":  "amadeus",
                        })
                    if results:
                        return results
        except Exception as e:
            log.debug("Amadeus autocomplete error: %s", e)

    # Fall back to local dictionary
    try:
        from core.geo_location import CITY_TO_AIRPORT
        kw_l = keyword.lower()
        local = [
            {"iata": code, "city": city.title(), "country": "",
             "display": f"{city.title()} ({code})", "source": "local"}
            for city, code in CITY_TO_AIRPORT.items()
            if kw_l in city
        ]
        local.sort(key=lambda x: (not x["city"].lower().startswith(kw_l), x["city"]))
        results = local[:limit]
    except Exception:
        pass

    return results
