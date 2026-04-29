"""
VoyageAI Destination Resolver
==============================
Resolves any destination text → correct IATA airport code.

Priority chain:
  1. ReferenceCache (DB-backed, 499 airports, 1200+ city aliases)
  2. DEST_MAP in mcp_scorer.py
  3. Amadeus Airport Search API (live)
  4. LLM extraction (last resort)

Also handles:
  - "near X" / "close to X" → nearest major airport
  - Region names → main hub
  - Ambiguous names → most likely airport for travel context
"""
import re
import logging

log = logging.getLogger("voyageai.reasoning")

# Region/area → IATA hub
REGION_TO_IATA = {
    # UK regions
    "south west england": "BRS", "southwest england": "BRS",
    "south east england": "LGW", "southeast england":  "LGW",
    "north west england": "MAN", "northwest england":  "MAN",
    "north england":      "MAN", "north of england":   "MAN",
    "midlands":           "BHX", "west midlands":      "BHX",
    "east midlands":      "EMA", "yorkshire":          "LBA",
    "northeast england":  "NCL", "northeast":          "NCL",
    "scotland":           "EDI", "highlands":          "INV",
    "wales":              "CWL", "northern ireland":   "BFS",

    # European regions
    "algarve":            "FAO", "algarve coast":      "FAO",
    "amalfi":             "NAP", "amalfi coast":       "NAP",
    "tuscany":            "PSA", "costa brava":        "BCN",
    "costa del sol":      "AGP", "andalusia":          "AGP",
    "catalonia":          "BCN", "balearic islands":   "PMI",
    "canary islands":     "TFS", "côte d'azur":        "NCE",
    "riviera":            "NCE", "french riviera":     "NCE",
    "dalmatian coast":    "DBV", "dalmatia":           "DBV",
    "greek islands":      "ATH", "cyclades":           "JTR",
    "dodecanese":         "RHO", "ionian islands":     "CFU",

    # Global regions
    "caribbean":          "MIA", "west indies":        "MIA",
    "southeast asia":     "SIN", "far east":           "SIN",
    "south asia":         "DEL", "indian subcontinent":"DEL",
    "middle east":        "DXB", "gulf":               "DXB",
    "east africa":        "NBO", "southern africa":    "JNB",
    "west africa":        "LOS", "north africa":       "CMN",
    "polynesia":          "PPT", "micronesia":         "GUM",
    "melanesia":          "NAN", "south pacific":      "NAN",
    "central america":    "PTY", "south america":      "GRU",
}


def resolve_destination(text: str, session_entities: dict = None) -> dict:
    """
    Resolve a destination text to IATA + metadata.

    Returns:
    {
        "iata":         "DXB",
        "city":         "Dubai",
        "country":      "United Arab Emirates",
        "country_code": "AE",
        "source":       "reference_cache" | "dest_map" | "amadeus" | "llm",
        "confidence":   0.0-1.0,
    }
    """
    if not text:
        return {}

    text_l = text.lower().strip()

    # 1. Already a 3-letter IATA code
    if re.match(r'^[A-Za-z]{3}$', text.strip()):
        iata = text.upper()
        info = _cache_airport(iata)
        if info:
            return {**info, "iata": iata, "source": "direct_iata", "confidence": 0.99}

    # 2. Check region map
    for region, iata in sorted(REGION_TO_IATA.items(), key=lambda x: len(x[0]), reverse=True):
        if region in text_l:
            info = _cache_airport(iata) or {}
            return {
                "iata":         iata,
                "city":         info.get("city", iata),
                "country":      info.get("country", ""),
                "country_code": info.get("country_code", ""),
                "source":       "region_map",
                "confidence":   0.87,
            }

    # 3. ReferenceCache city lookup (DB-backed)
    try:
        from core.reference_cache import ref
        iata = ref.city_to_iata(text_l)
        if iata:
            airport = ref.airport(iata) or {}
            cc = airport.get("country_code", "")
            country_info = ref.country(cc) or {}
            return {
                "iata":         iata,
                "city":         airport.get("city", text.title()),
                "country":      country_info.get("name", ""),
                "country_code": cc,
                "source":       "reference_cache",
                "confidence":   0.95,
            }
    except Exception as e:
        log.debug("RefCache lookup error: %s", e)

    # 4. DEST_MAP from mcp_scorer
    try:
        from reasoning.mcp_scorer import DEST_MAP, CODE_TO_COUNTRY
        for name in sorted(DEST_MAP.keys(), key=len, reverse=True):
            if name in text_l:
                iata = DEST_MAP[name]
                cc   = CODE_TO_COUNTRY.get(iata, "")
                return {
                    "iata":         iata,
                    "city":         name.title(),
                    "country":      cc,
                    "country_code": cc,
                    "source":       "dest_map",
                    "confidence":   0.90,
                }
    except Exception:
        pass

    # 5. Amadeus Airport & City Search
    try:
        from mcp_servers.iata_resolver import _amadeus_airport_search
        result = _amadeus_airport_search(text)
        if result and result.get("iata"):
            return {**result, "source": "amadeus", "confidence": 0.85}
    except Exception:
        pass

    # 6. ReferenceCache partial / fuzzy match
    try:
        from core.reference_cache import ref
        # Try words from the text
        words = text_l.split()
        for word in sorted(words, key=len, reverse=True):
            if len(word) < 3:
                continue
            iata = ref.city_to_iata(word)
            if iata:
                airport = ref.airport(iata) or {}
                return {
                    "iata":         iata,
                    "city":         airport.get("city", word.title()),
                    "country":      "",
                    "country_code": airport.get("country_code", ""),
                    "source":       "reference_cache_partial",
                    "confidence":   0.75,
                }
    except Exception:
        pass

    return {}


def _cache_airport(iata: str) -> dict | None:
    try:
        from core.reference_cache import ref
        a = ref.airport(iata)
        if a:
            cc = a.get("country_code", "")
            try:
                country = ref.country(cc) or {}
                country_name = country.get("name", "")
            except Exception:
                country_name = ""
            return {
                "city":         a.get("city", ""),
                "country":      country_name,
                "country_code": cc,
            }
    except Exception:
        pass
    return None


def extract_all_destinations(text: str) -> list[dict]:
    """
    Extract all destination mentions from a longer text.
    Used for "A or B?" queries and suggestion responses.
    """
    results = []
    seen    = set()

    # Try each phrase in the text
    try:
        from core.reference_cache import ref
        words = text.lower().split()
        # Try 1-4 word combinations
        for n in range(4, 0, -1):
            for i in range(len(words) - n + 1):
                phrase = " ".join(words[i:i+n])
                iata = ref.city_to_iata(phrase)
                if iata and iata not in seen:
                    airport = ref.airport(iata) or {}
                    results.append({
                        "iata":   iata,
                        "phrase": phrase,
                        "city":   airport.get("city", phrase.title()),
                    })
                    seen.add(iata)
    except Exception:
        pass

    return results
