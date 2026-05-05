"""
VoyageAI Context Engine — Single source of truth for understanding user intent.

Replaces the fragmented extraction pipeline with one clear function:
  understand(message, history, plan, session_id) → action dict

The LLM sees the full conversation and returns a structured action.
Regional awareness resolves "North India", "coastal Spain" etc. to specific cities.
Falls back to deterministic regex when LLM is unavailable.
"""
import json, re, logging
from datetime import datetime, timedelta

log = logging.getLogger("voyageai.reasoning")
_TODAY = datetime.now()

# ─── Regional resolution — "North India" → DEL etc. ─────────
REGION_MAP: dict[str, str] = {
    # India regions
    "north india": "DEL", "northern india": "DEL",
    "south india": "COK", "southern india": "MAA",
    "east india": "CCU",  "eastern india": "CCU",
    "west india": "BOM",  "western india": "BOM",
    "central india": "NAG",
    "rajasthan": "JAI",   "gujarat": "AMD",
    "kerala": "COK",      "goa": "GOI",
    "karnataka": "BLR",   "tamil nadu": "MAA",
    "andhra pradesh": "HYD", "telangana": "HYD",
    "maharashtra": "BOM", "punjab": "ATQ",
    "uttarakhand": "DED", "himachal pradesh": "DHM",
    "kashmir": "SXR",     "ladakh": "IXL",
    "northeast india": "GAU", "assam": "GAU",
    "sikkim": "IXB",      "west bengal": "CCU",
    "odisha": "BBI",      "madhya pradesh": "BHO",
    "uttar pradesh": "LKO",
    # UK regions
    "scottish highlands": "INV", "highlands": "INV",
    "scottish islands": "SYY",   "orkney": "KOI",
    "lake district": "MAN",      "cornwall": "BOH",
    "cotswolds": "BRS",
    # Europe regions
    "amalfi coast": "NAP", "amalfi": "NAP",
    "tuscany": "PSA",      "sicily": "CTA",
    "sardinia": "CAG",     "corsica": "AJA",
    "algarve": "FAO",      "douro valley": "OPO",
    "costa del sol": "AGP","andalusia": "AGP",
    "catalonia": "BCN",    "basque country": "BIO",
    "provence": "MRS",     "normandy": "CDG",
    "brittany": "BES",     "french riviera": "NCE",
    "cote d'azur": "NCE",  "côte d'azur": "NCE",
    "riviera": "NCE",
    "dalmatian coast": "DBV", "dalmatia": "DBV",
    "greek islands": "ATH", "cyclades": "JTR",
    "dodecanese": "RHO",   "ionian": "CFU",
    "canary islands": "TFS", "balearic islands": "PMI",
    # Global regions
    "southeast asia": "SIN", "far east": "SIN",
    "middle east": "DXB",   "gulf states": "DXB",
    "east africa": "NBO",   "southern africa": "JNB",
    "west africa": "LOS",   "north africa": "CMN",
    "caribbean": "MIA",     "west indies": "MIA",
    "south america": "GRU", "central america": "PTY",
    "polynesia": "PPT",     "south pacific": "NAN",
    # Spanish cities (common with/without accents)
    "san sebastian": "EAS", "san sebastián": "EAS", "donostia": "EAS",
    "basque country": "EAS", "basque": "EAS", "pais vasco": "EAS",
    "bilbao": "BIO", "vitoria": "VIT",
    "mallorca": "PMI", "majorca": "PMI",
    "menorca": "MAH", "ibiza": "IBZ",
    "lanzarote": "ACE", "fuerteventura": "FUE", "gran canaria": "LPA",
    "seville": "SVQ", "sevilla": "SVQ",
    "granada": "GRX", "malaga": "AGP", "marbella": "AGP",
    "valencia": "VLC", "alicante": "ALC", "murcia": "MJV",
    # Italian cities
    "amalfi": "NAP", "positano": "NAP", "capri": "NAP",
    "cinque terre": "GEN", "portofino": "GOA",
    "sicily": "CTA", "palermo": "PMO", "catania": "CTA",
    "sardinia": "CAG", "cagliari": "CAG",
    "venice": "VCE", "venezia": "VCE",
    "florence": "PSA", "firenze": "PSA",
    # French destinations
    "nice": "NCE", "cannes": "NCE", "monaco": "NCE",
    "bordeaux": "BOD", "lyon": "LYS", "marseille": "MRS",
    "strasbourg": "SXB", "nantes": "NTE",
    # Other popular destinations
    "reykjavik": "KEF", "dubrovnik": "DBV",
    "split": "SPU", "zadar": "ZAD", "hvar": "SPU",
    "kotor": "TIV", "budva": "TGD",
    "santorini": "JTR", "mykonos": "JMK",
    "rhodes": "RHO", "crete": "HER", "corfu": "CFU",
    "zakynthos": "ZTH", "zante": "ZTH", "kos": "KGS",
    "skiathos": "JSI", "lefkada": "PVK",
    "funchal": "FNC", "madeira": "FNC",
    "azores": "PDL",

    # Country to hub (for "Spain", "India" etc.)
    "spain": "MAD",  "france": "CDG", "italy": "FCO",
    "germany": "FRA","greece": "ATH", "portugal": "LIS",
    "turkey": "IST", "egypt": "CAI",  "morocco": "CMN",
    "thailand": "BKK","japan": "NRT", "china": "PEK",
    "india": "DEL",  "indonesia": "CGK","malaysia": "KUL",
    "singapore": "SIN","australia": "SYD","new zealand": "AKL",
    "canada": "YYZ", "mexico": "MEX", "brazil": "GRU",
    "argentina": "EZE","peru": "LIM", "colombia": "BOG",
    "south africa": "JNB","kenya": "NBO","tanzania": "DAR",
    "uae": "DXB",   "dubai": "DXB",  "qatar": "DOH",
    "saudi arabia": "RUH","israel": "TLV","jordan": "AMM",
    "vietnam": "SGN","cambodia": "PNH","nepal": "KTM",
    "sri lanka": "CMB","maldives": "MLE","pakistan": "KHI",
}

# ─── Holiday dates ────────────────────────────────────────────
def _next_date(month: int, day: int) -> str:
    y = _TODAY.year
    d = datetime(y, month, day)
    if d < _TODAY: d = datetime(y + 1, month, day)
    return d.strftime("%Y-%m-%d")

HOLIDAY_DATES = {
    "christmas":      {"departure_date": _next_date(12,25), "nights": 7},
    "coming christmas":{"departure_date": _next_date(12,25), "nights": 7},
    "christmas week": {"departure_date": _next_date(12,23), "nights": 7},
    "new year":       {"departure_date": _next_date(12,29), "nights": 7},
    "easter":         {"departure_date": _next_date(3,28),  "nights": 10},
    "half term":      {"departure_date": _next_date(5,26),  "nights": 7},
    "summer":         {"departure_date": _next_date(7,1),   "nights": 14},
    "next summer":    {"departure_date": _next_date(7,1),   "nights": 14},
    "winter":         {"departure_date": _next_date(12,20), "nights": 7},
    "january": {"departure_date": _next_date(1,1)},
    "february":{"departure_date": _next_date(2,1)},
    "march":   {"departure_date": _next_date(3,1)},
    "april":   {"departure_date": _next_date(4,1)},
    "may":     {"departure_date": _next_date(5,1)},
    "june":    {"departure_date": _next_date(6,1)},
    "july":    {"departure_date": _next_date(7,1)},
    "august":  {"departure_date": _next_date(8,1)},
    "september":{"departure_date":_next_date(9,1)},
    "october": {"departure_date": _next_date(10,1)},
    "november":{"departure_date": _next_date(11,1)},
    "december":{"departure_date": _next_date(12,1)},
}


# ─── LLM prompt ───────────────────────────────────────────────
_SYSTEM = f"""You are VoyageAI travel assistant. Today: {_TODAY.strftime('%Y-%m-%d')}.

Analyse the FULL conversation and understand exactly what the user wants.

CRITICAL: SUGGESTION vs MODIFICATION detection:
- "find holy places in middle east" → action: "suggest" (user wants options, NOT changing guests)
- "show me beach destinations in Asia" → action: "suggest"
- "find some options" → action: "suggest"
- "change dates to Christmas" → action: "modify", subtype: "dates"
- "upgrade to 5 star" → action: "modify", subtype: "hotel"
- "6 people instead" → action: "modify", subtype: "guests"

Key rule: "find/show/suggest X place/destination" = ALWAYS suggest, NEVER modify.
The word "some" in "find some holy place" refers to multiple destinations, NOT guests.

Resolve vague regions to a SPECIFIC IATA airport code:
- "North India" / "holy places India" → VNS, ATQ, DED, HRW, GAY
- "Middle East holy places" → AMM (Jerusalem), TLV, BEY, MCT
- "South India" → COK, MAA, BLR, HYD
- "coastal Spain" → AGP, BCN, PMI, TFS

CRITICAL RULES:
1. For destination changes — NEVER return the current plan's destination
2. Pick ONE specific city, not a country or region
3. Understand sentiment: "somewhere peaceful" ≠ previous busy destination  
4. Read the FULL history — user may be answering a previous question
5. If user says "different destination in X region" → pick city in that region

Return ONLY valid JSON:
{{
  "action": "plan|modify|suggest|clarify|confirm|cancel",
  "subtype": "destination|dates|guests|hotel|flight|budget|null",
  "destination": "City name or null",
  "destination_iata": "IATA or null",
  "departure_date": "YYYY-MM-DD or null",
  "nights": number_or_null,
  "return_date": "YYYY-MM-DD or null",
  "guests": number_or_null,
  "adults": number_or_null,
  "children": number_or_null,
  "budget_gbp": number_or_null,
  "min_hotel_stars": number_or_null,
  "direct_flight": true_false_or_null,
  "response": "Short natural reply to user — DO NOT mention old destination for destination changes",
  "reasoning": "Brief: what you understood"
}}"""

_USER_TPL = """CURRENT PLAN:
{plan}

CONVERSATION (most recent last):
{history}

USER: "{message}"

What does the user want? Return JSON action."""

# Override the legacy prompt with a dynamic, LLM-first intent parser.
_SYSTEM = f"""You are VoyageAI travel assistant. Today: {_TODAY.strftime('%Y-%m-%d')}.

Analyse the FULL conversation and understand exactly what the user wants to do.

Decide dynamically:
- action="plan" when the user wants a concrete itinerary built
- action="modify" when they want to change an existing trip
- action="suggest" when they want destination ideas/options and have not picked one yet
- action="clarify" when essential information is still missing
- action="confirm" when they are approving the current plan
- action="cancel" when they are abandoning the current plan

For modifications, return ONLY the changed fields in `changes`.
For suggestions, leave destination and destination_iata null unless the user explicitly picked one option.
Read the full history and current plan before deciding.

Return ONLY valid JSON:
{{
  "action": "plan|modify|suggest|clarify|confirm|cancel",
  "subtype": "destination|dates|guests|hotel|flight|budget|null",
  "changes": {{
    "destination": "City name or null",
    "destination_iata": "IATA or null",
    "departure_date": "YYYY-MM-DD or null",
    "nights": number_or_null,
    "return_date": "YYYY-MM-DD or null",
    "guests": number_or_null,
    "adults": number_or_null,
    "children": number_or_null,
    "budget_gbp": number_or_null,
    "min_hotel_stars": number_or_null,
    "direct_flight": true_false_or_null
  }},
  "destination": "City name or null",
  "destination_iata": "IATA or null",
  "departure_date": "YYYY-MM-DD or null",
  "nights": number_or_null,
  "return_date": "YYYY-MM-DD or null",
  "guests": number_or_null,
  "adults": number_or_null,
  "children": number_or_null,
  "budget_gbp": number_or_null,
  "min_hotel_stars": number_or_null,
  "direct_flight": true_false_or_null,
  "response": "Short natural reply to user",
  "reasoning": "Brief: what you understood"
}}"""


def _is_category_suggestion_query(text: str) -> bool:
    text_l = (text or "").lower()
    modification_markers = (
        "change the plan", "change plan", "change dates", "change date",
        "different dates", "move the trip", "reschedule", "postpone",
        "bring it forward", "for christmas", "christmas holidays",
    )
    if any(marker in text_l for marker in modification_markers):
        return False

    concrete_plan_markers = (
        "please build me a complete personalised itinerary",
        "complete personalised itinerary",
        "build me a complete itinerary",
        "build a complete itinerary",
        "plan a trip to",
        "book a trip to",
        "travel to ",
        "go to ",
        "visit ",
        "change destination to",
        "switch to ",
        "instead of ",
        "can we go to ",
    )
    if any(marker in text_l for marker in concrete_plan_markers):
        return False

    if re.search(r"\b[A-Z]{3}\b", text):
        return False

    suggestion_markers = (
        "suggest", "recommend", "options", "ideas", "which one", "which destination",
        "where should", "where can", "where to", "help me choose", "looking for",
        "show me", "find me", "need ideas",
    )
    generic_destination_markers = (
        "destination", "destinations", "place", "places", "city", "cities",
        "location", "locations", "holiday", "trip", "vacation", "getaway", "break",
        "somewhere",
    )

    has_suggestion_marker = any(term in text_l for term in suggestion_markers)
    has_generic_destination_marker = any(term in text_l for term in generic_destination_markers)
    wants_multiple = any(term in text_l for term in ("some", "few", "multiple", "options", "ideas"))
    has_concrete_trip_params = bool(re.search(
        r"\d+\s*nights?|\d+\s*weeks?|\d+\s*(people|guests|adults?|children|kids?)|"
        r"[£$]\s*\d+|"
        r"\b(january|february|march|april|may|june|july|august|september|october|november|december|christmas|easter|summer|winter)\b|"
        r"20\d{2}-\d{2}-\d{2}",
        text_l
    ))
    candidate = _extract_destination_candidate(text)
    should_attempt_destination_resolution = bool(candidate)
    specific_iata = None
    if should_attempt_destination_resolution:
        _, specific_iata = resolve_destination(candidate)
    has_specific_destination = bool(specific_iata) and not any(
        region_term in text_l for region_term in (
            "india", "europe", "asia", "africa", "middle east", "caribbean",
            "north india", "south india", "east india", "west india",
        )
    )

    if has_specific_destination:
        if has_concrete_trip_params:
            return False
        if any(marker in text_l for marker in ("plan", "build", "book", "travel to", "trip to", "holiday in")):
            return False

    if has_concrete_trip_params and not has_suggestion_marker and not wants_multiple and has_specific_destination:
        return False

    short_open_ended_query = len(text_l.split()) <= 8 and not has_specific_destination and not has_concrete_trip_params
    direct_build_marker = any(marker in text_l for marker in (
        "build", "plan", "book", "itinerary", "package",
    ))
    if direct_build_marker and has_specific_destination:
        return False

    generic_request = not has_specific_destination and (
        has_suggestion_marker
        or has_generic_destination_marker
        or wants_multiple
        or short_open_ended_query
    )

    return generic_request


def _normalize_category_suggestion(parsed: dict, message: str) -> dict:
    if not _is_category_suggestion_query(message):
        return parsed

    text_l = (message or "").lower()
    if any(marker in text_l for marker in (
        "change the plan", "change plan", "change dates", "change date",
        "different dates", "reschedule", "postpone",
    )):
        return parsed

    if parsed.get("action") in {"plan", "modify"} or parsed.get("subtype") == "destination":
        parsed["action"] = "suggest"
        parsed["subtype"] = "destination"
        parsed["destination"] = None
        parsed["destination_iata"] = None
        parsed["response"] = parsed.get("response") or "I can suggest a few destinations that fit that theme."
        parsed["reasoning"] = "User is asking for themed destination suggestions, not a single fixed itinerary."
    return parsed


def _hydrate_action(parsed: dict) -> dict:
    """Normalize LLM output into the flat action shape used by the rest of the backend."""
    if not isinstance(parsed, dict):
        return parsed

    changes = parsed.get("changes")
    if isinstance(changes, dict):
        for key, value in changes.items():
            if parsed.get(key) is None and value is not None:
                parsed[key] = value

    if parsed.get("action") == "modify" and not parsed.get("subtype"):
        if parsed.get("destination_iata") or parsed.get("destination"):
            parsed["subtype"] = "destination"
        elif parsed.get("departure_date") or parsed.get("return_date") or parsed.get("nights"):
            parsed["subtype"] = "dates"
        elif parsed.get("guests") is not None or parsed.get("adults") is not None or parsed.get("children") is not None:
            parsed["subtype"] = "guests"
        elif parsed.get("budget_gbp") is not None:
            parsed["subtype"] = "budget"
        elif parsed.get("min_hotel_stars") is not None:
            parsed["subtype"] = "hotel"
        elif parsed.get("direct_flight") is not None:
            parsed["subtype"] = "flight"

    if parsed.get("action") == "suggest":
        parsed["destination"] = None
        parsed["destination_iata"] = None

    return parsed


def _has_trip_constraints(text: str) -> bool:
    text_l = (text or "").lower()
    return bool(re.search(
        r"\d+\s*nights?|\d+\s*weeks?|\d+\s*(people|guests|adults?|children|kids?)|"
        r"[£$]\s*\d+|"
        r"\b(january|february|march|april|may|june|july|august|september|october|november|december|christmas|easter|summer|winter)\b|"
        r"20\d{2}-\d{2}-\d{2}|"
        r"\bdirect\b|\bnonstop\b|\b5\s*star\b|\b4\s*star\b|\bbudget\b",
        text_l
    ))


def _extract_destination_candidate(text: str) -> str | None:
    text = (text or "").strip()
    if not text:
        return None

    stop_candidates = {
        "can we look", "can we look for", "can we", "i want to change",
        "i want to change to", "change the plan", "change plan",
        "show me", "find me", "find some", "look for", "suggest",
        "recommend", "help me choose",
    }

    patterns = [
        r"\b(?:trip to|travel to|go to|visit|holiday in|destination in|fly to)\s+([A-Za-z][A-Za-z\s'-]{1,40}?)(?:\s+for\b|\s+in\b|\s+with\b|\s+during\b|\s+from\b|$)",
        r"^([A-Z][A-Za-z\s'-]{1,40}?)(?:\s+for\b|\s+in\b|\s+with\b|\s+during\b|\s+from\b|$)",
    ]
    for pattern in patterns:
        m = re.search(pattern, text)
        if m:
            candidate = (m.group(1) or "").strip(" ,.-")
            candidate_l = candidate.lower()
            if candidate and len(candidate.split()) <= 4 and candidate_l not in stop_candidates:
                return candidate
    return None


def _resolve_explicit_destination(parsed: dict, message: str, plan_text: str) -> dict:
    """Resolve explicit destination text into an IATA code before downstream routing uses stale session state."""
    if not isinstance(parsed, dict):
        return parsed

    if parsed.get("action") == "suggest":
        return parsed

    current_iata = None
    m = re.search(r'\(([A-Z]{3})\)', plan_text)
    if m:
        current_iata = m.group(1)

    destination = (parsed.get("destination") or "").strip()
    destination_iata = (parsed.get("destination_iata") or "").strip()
    explicit_iata_match = re.search(r'\b([A-Z]{3})\b', message or "")

    if explicit_iata_match and not destination_iata:
        parsed["destination_iata"] = explicit_iata_match.group(1)
        destination_iata = parsed["destination_iata"]

    if destination and not destination_iata:
        exclude_iata = current_iata if parsed.get("action") == "modify" else None
        city, iata = resolve_destination(destination, exclude_iata=exclude_iata)
        if iata:
            parsed["destination"] = city or destination
            parsed["destination_iata"] = iata
            return parsed

    if parsed.get("action") == "plan" and not parsed.get("destination_iata"):
        candidate = _extract_destination_candidate(message)
        if candidate:
            city, iata = resolve_destination(candidate)
            if iata:
                parsed["destination"] = city or candidate
                parsed["destination_iata"] = iata
    return parsed


def understand(
    message: str,
    history: list,
    plan: dict | None,
    session_id: str,
) -> dict:
    """
    Understand a user message in full context.
    Returns a structured action dict ready for chat.py to execute.
    """
    # Build plan summary
    plan_text = _plan_text(plan)

    # Format recent history (last 8 turns)
    hist_text = _hist_text(history[-8:])

    # Try real LLM first
    llm_result = _try_llm(plan_text, hist_text, message, session_id)
    if llm_result:
        return llm_result

    # Deterministic fallback — always correct, just less nuanced
    return _deterministic(message, history, plan, session_id)


def resolve_destination(text: str, exclude_iata: str = None) -> tuple[str | None, str | None]:
    """
    Resolve any destination text → (city_name, IATA).
    exclude_iata: never return this code (used to prevent returning current plan's destination).
    """
    text_l = text.lower().strip()

    # 1. Reference cache covers all region aliases (loaded from DB including region_map entries)
    # No separate REGION_MAP lookup needed — ref.city_to_iata() handles "north india" → DEL
    # (the DB was populated from the old REGION_MAP on first run)

    # 2. Reference cache (includes Indian holy cities loaded from DB)
    try:
        from core.reference_cache import ref
        iata = ref.city_to_iata(text_l)
        if iata and iata != exclude_iata:
            ap = ref.airport(iata) or {}
            return ap.get("city", text.title()), iata
    except Exception:
        pass

    # 2b. Direct DB lookup (covers cities not in in-memory cache yet)
    try:
        from data.conversation_store import get_db
        conn = get_db()
        row  = conn.execute(
            "SELECT iata FROM ref_city_iata WHERE alias=? COLLATE NOCASE", (text_l,)
        ).fetchone()
        conn.close()
        if row and row[0] != exclude_iata:
            return text.title(), row[0]
    except Exception:
        pass

    # 3. Word-by-word
    words = text_l.split()
    for n in range(min(4, len(words)), 0, -1):
        for i in range(len(words) - n + 1):
            phrase = " ".join(words[i:i+n])
            if phrase in REGION_MAP:
                iata = REGION_MAP[phrase]
                if iata != exclude_iata:
                    return phrase.title(), iata
            try:
                from core.reference_cache import ref
                iata = ref.city_to_iata(phrase)
                if iata and iata != exclude_iata:
                    ap = ref.airport(iata) or {}
                    return ap.get("city", phrase.title()), iata
            except Exception:
                pass
            try:
                from data.conversation_store import get_db
                conn = get_db()
                row  = conn.execute(
                    "SELECT iata FROM ref_city_iata WHERE alias=? COLLATE NOCASE", (phrase,)
                ).fetchone()
                conn.close()
                if row and row[0] != exclude_iata:
                    return phrase.title(), row[0]
            except Exception:
                pass

    # ── Nearest airport fallback ────────────────────────────────────────────
    # Nothing resolved — try the nearest airport module
    try:
        from reasoning.nearest_airport import find_nearest_airport
        result = find_nearest_airport(text)
        if result:
            log.info("Nearest airport resolved: %s → %s (%s, %.0fkm by %s)",
                     text, result.iata, result.airport_city,
                     result.distance_km, result.transfer_mode)
            return result.airport_city, result.iata
    except Exception as _e:
        pass

    return None, None


def _try_llm(plan_text: str, hist_text: str, message: str, session_id: str) -> dict | None:
    """Attempt LLM understanding, skip template provider."""
    try:
        from llm.waterfall import get_waterfall
        from config import Config
        wf = get_waterfall()
        user = _USER_TPL.format(plan=plan_text, history=hist_text, message=message)
        for pname in (Config.LLM_WATERFALL if hasattr(Config,'LLM_WATERFALL') else ["groq","gemini","anthropic"]):
            if pname == "template":
                continue
            provider = getattr(wf, "providers", {}).get(pname)
            if not provider or not provider.is_available():
                continue
            try:
                resp = provider.complete(_SYSTEM, user, max_tokens=500, temperature=0.1)
                if resp.success and resp.text:
                    parsed = _parse_json(resp.text)
                    if parsed:
                        parsed = _hydrate_action(parsed)
                        parsed = _resolve_explicit_destination(parsed, message, plan_text)
                        parsed = _normalize_category_suggestion(parsed, message)
                        # Post-process: ensure destination is not the current plan's destination
                        parsed = _validate_destination_change(parsed, plan_text, message)
                        parsed["_source"] = pname
                        log.info("Context LLM success", extra={
                            "session": session_id, "provider": pname,
                            "action": parsed.get("action"),
                            "dest":   parsed.get("destination_iata"),
                            "reason": parsed.get("reasoning","")[:60],
                        })
                        return parsed
            except Exception as e:
                log.debug("LLM provider %s error: %s", pname, e)
    except Exception as e:
        log.debug("LLM unavailable: %s", e)
    return None


def _validate_destination_change(parsed: dict, plan_text: str, message: str) -> dict:
    """
    Ensure destination changes never return the current plan's destination.
    Also resolve regional terms to specific cities.
    """
    if parsed.get("action") == "suggest" or _is_category_suggestion_query(message):
        parsed["destination"] = None
        parsed["destination_iata"] = None
        return parsed

    if parsed.get("subtype") != "destination":
        return parsed

    # Extract current plan's IATA from plan_text
    current_iata = None
    m = re.search(r'\(([A-Z]{3})\)', plan_text)
    if m:
        current_iata = m.group(1)

    # If LLM returned same destination → fix it
    if parsed.get("destination_iata") == current_iata:
        city, iata = resolve_destination(message, exclude_iata=current_iata)
        if iata:
            parsed["destination_iata"] = iata
            parsed["destination"]      = city

    # If IATA is still None for destination change → resolve from message
    if not parsed.get("destination_iata") and parsed.get("subtype") == "destination":
        city, iata = resolve_destination(message, exclude_iata=current_iata)
        if iata:
            parsed["destination_iata"] = iata
            parsed["destination"]      = city

    return parsed


def _deterministic(message: str, history: list, plan: dict | None, session_id: str) -> dict:
    """
    Rule-based understanding — always works, never hallucinates.
    Uses the message + conversation context + plan.
    """
    text_l = message.lower().strip()
    has_plan = bool(plan)

    # Current plan's IATA (for exclusion in destination changes)
    current_iata = None
    if plan:
        current_iata = plan.get("intent", {}).get("city_code")

    result: dict = {"action": "plan", "subtype": None, "_source": "deterministic"}

    # ── CANCEL ────────────────────────────────────────────────
    if any(p in text_l for p in ["cancel","start over","start again","forget it","scrap","never mind"]):
        return {**result, "action": "cancel"}

    # ── CONFIRM ───────────────────────────────────────────────
    if has_plan and len(text_l.split()) <= 6 and any(
        p in text_l for p in ["yes","ok","okay","book","confirm","perfect","great","looks good","go ahead","proceed"]
    ):
        return {**result, "action": "confirm"}

    # ── DESTINATION CHANGE ────────────────────────────────────
    dest_signals = [
        "change destination", "different destination", "change to",
        "switch to", "go to", "visit", "instead of", "rather than",
        "how about", "what about", "can we go to",
    ]
    regional_signals = [
        "north india", "south india", "east india", "west india",
        "north of india", "south of india", "northern india", "southern india",
        "rajasthan", "kerala", "punjab", "kashmir", "ladakh", "uttarakhand",
        "himalaya", "himachal", "northeast india",
    ]
    is_dest_change = (
        any(s in text_l for s in dest_signals) or
        (any(s in text_l for s in regional_signals) and has_plan) or
        # User answering a pending clarification about destination
        ("different" in text_l and "destination" in text_l) or
        ("north india" in text_l or "south india" in text_l)
    )

    if is_dest_change and has_plan:
        city, iata = resolve_destination(message, exclude_iata=current_iata)
        result.update({
            "action":          "modify",
            "subtype":         "destination",
            "destination":     city,
            "destination_iata":iata,
            "response":        f"Searching for options in {city or 'your requested destination'}...",
            "reasoning":       f"User wants destination changed to {city or message}",
        })
        return result

    # ── DATE CHANGE ───────────────────────────────────────────
    date_signals = [
        "change dates", "change date", "different dates",
        "christmas", "new year", "easter", "half term", "summer", "winter",
        "in january","in february","in march","in april","in may","in june",
        "in july","in august","in september","in october","in november","in december",
        "next month", "this weekend",
    ]
    if has_plan and any(s in text_l for s in date_signals):
        date_info = {}
        for key in sorted(HOLIDAY_DATES, key=len, reverse=True):
            if key in text_l:
                date_info = dict(HOLIDAY_DATES[key])
                break
        # Explicit nights/weeks
        n_m = re.search(r'(?:for\s+)?(\d+)\s*(night|week)s?', text_l)
        if n_m:
            n = int(n_m.group(1))
            date_info["nights"] = n * 7 if "week" in n_m.group(2) else n
        # ISO date in message
        iso = re.search(r'20\d\d-\d{2}-\d{2}', message)
        if iso:
            date_info["departure_date"] = iso.group(0)
        # Month + day
        for mname, mnum in [("january",1),("february",2),("march",3),("april",4),
                             ("may",5),("june",6),("july",7),("august",8),
                             ("september",9),("october",10),("november",11),("december",12)]:
            if mname in text_l and "departure_date" not in date_info:
                y = _TODAY.year
                d = datetime(y, mnum, 1)
                if d < _TODAY: d = datetime(y+1, mnum, 1)
                day_m = re.search(r'(\d{1,2})(?:st|nd|rd|th)?', text_l)
                if day_m:
                    try: d = d.replace(day=int(day_m.group(1)))
                    except ValueError: pass
                date_info["departure_date"] = d.strftime("%Y-%m-%d")
                break
        result.update({"action":"modify","subtype":"dates",**date_info})
        return result

    # ── GUEST CHANGE ──────────────────────────────────────────
    guest_signals = ["more people","fewer people","change guests","update guests",
                     "adults","children","kids","solo","couple","family of"]
    if has_plan and any(s in text_l for s in guest_signals) and re.search(r'\d', text_l):
        adults_m  = re.search(r'(\d+)\s*adults?', text_l)
        child_m   = re.search(r'(\d+)\s*(?:children|child|kids?)', text_l)
        people_m  = re.search(r'(\d+)\s*(?:people|guests|of us)', text_l)
        adults    = int(adults_m.group(1)) if adults_m else None
        children  = int(child_m.group(1))  if child_m  else None
        guests    = (adults or 0) + (children or 0) if adults else int(people_m.group(1)) if people_m else None
        result.update({"action":"modify","subtype":"guests","guests":guests,
                       "adults":adults,"children":children})
        return result

    # ── HOTEL CHANGE ─────────────────────────────────────────
    if has_plan and any(s in text_l for s in ["hotel","star","upgrade","5 star","4 star","resort","pool","luxury","budget hotel"]):
        star_m = re.search(r'(\d)\s*[\-\s]?star', text_l)
        stars  = int(star_m.group(1)) if star_m else (5 if "luxury" in text_l else None)
        result.update({"action":"modify","subtype":"hotel","min_hotel_stars":stars})
        return result

    # ── BUDGET CHANGE ─────────────────────────────────────────
    if has_plan and any(s in text_l for s in ["budget","£","cheaper","more expensive","spend","afford"]):
        b_m    = re.search(r'[£$](\d[\d,]*)', message)
        budget = int(b_m.group(1).replace(",","")) if b_m else None
        result.update({"action":"modify","subtype":"budget","budget_gbp":budget})
        return result

    # ── EXTRACT PLAN PARAMS ───────────────────────────────────
    if _is_category_suggestion_query(message):
        return {
            **result,
            "action": "suggest",
            "subtype": "destination",
            "destination": None,
            "destination_iata": None,
            "response": "I can suggest a few destinations that fit what you are asking for.",
            "reasoning": "User is asking for destination ideas rather than a fully specified itinerary.",
        }

    iata_check = None
    candidate = _extract_destination_candidate(message)
    if candidate:
        _, iata_check = resolve_destination(candidate)
    if not has_plan and not iata_check and _has_trip_constraints(message):
        return {
            **result,
            "action": "clarify",
            "subtype": "destination",
            "response": "I have the trip details, but I still need a destination. Tell me the place you want, or ask for suggestions.",
            "reasoning": "User gave trip constraints but did not choose a specific destination.",
        }

    # For fresh plan requests: extract destination, dates, guests, budget
    city, iata = resolve_destination(message)
    date_info  = {}
    for key in sorted(HOLIDAY_DATES, key=len, reverse=True):
        if key in text_l:
            date_info = dict(HOLIDAY_DATES[key])
            break
    n_m = re.search(r'(\d+)\s*(night|week)s?', text_l)
    if n_m:
        n = int(n_m.group(1))
        date_info["nights"] = n * 7 if "week" in n_m.group(2) else n
    iso = re.search(r'20\d\d-\d{2}-\d{2}', message)
    if iso: date_info["departure_date"] = iso.group(0)
    for mname, mnum in [("january",1),("february",2),("march",3),("april",4),
                         ("may",5),("june",6),("july",7),("august",8),
                         ("september",9),("october",10),("november",11),("december",12)]:
        if mname in text_l and "departure_date" not in date_info:
            y = _TODAY.year
            d = datetime(y, mnum, 1)
            if d < _TODAY: d = datetime(y+1, mnum, 1)
            date_info["departure_date"] = d.strftime("%Y-%m-%d")
            break
    a_m   = re.search(r'(\d+)\s*adults?', text_l)
    c_m   = re.search(r'(\d+)\s*(?:children|child|kids?)', text_l)
    p_m   = re.search(r'(\d+)\s*(?:people|guests|of us|passengers)', text_l)
    adults   = int(a_m.group(1)) if a_m else None
    children = int(c_m.group(1)) if c_m else None
    guests   = ((adults or 0)+(children or 0)) if adults else (int(p_m.group(1)) if p_m else None)
    if "solo" in text_l or "just me" in text_l or "by myself" in text_l:
        guests = 1; adults = 1; children = 0
    elif "couple" in text_l or "two of us" in text_l or "just us" in text_l:
        guests = 2; adults = 2; children = 0
    b_m    = re.search(r'[£$](\d[\d,]*)', message)
    budget = int(b_m.group(1).replace(",","")) if b_m else None
    star_m = re.search(r'(\d)\s*[\-\s]?star', text_l)
    stars  = int(star_m.group(1)) if star_m else None

    return {
        **result,
        "action":           "plan",
        "destination":      city,
        "destination_iata": iata,
        **date_info,
        "guests":           guests,
        "adults":           adults,
        "children":         children,
        "budget_gbp":       budget,
        "min_hotel_stars":  stars,
        "_source":          "deterministic",
    }


def _parse_json(text: str) -> dict | None:
    try:
        text = text.strip()

        # Strip markdown fences
        if "```" in text:
            parts = text.split("```")
            text = parts[1] if len(parts) >= 3 else text
            if text.startswith("json"):
                text = text[4:]
        text = text.strip()

        # Always extract the FIRST complete {...} object — ignore leading arrays or trailing text
        # This handles LLM responses like: ["Dubai"], "summary": "..." or mixed output
        s = text.find("{")
        e = text.rfind("}")
        if s == -1 or e == -1 or e <= s:
            return None

        json_str = text[s:e+1]

        # Verify it's a valid JSON object (not just a fragment)
        data = json.loads(json_str)
        if not isinstance(data, dict):
            return None

        # Normalise nulls
        for k, v in list(data.items()):
            if v in ("null", "none", "", "N/A", "n/a"):
                data[k] = None

        # Validate IATA
        if data.get("destination_iata"):
            iata = str(data["destination_iata"]).upper().strip()
            data["destination_iata"] = iata if re.match(r"^[A-Z]{3}$", iata) else None

        # Validate date
        if data.get("departure_date"):
            try:
                datetime.strptime(str(data["departure_date"]), "%Y-%m-%d")
            except ValueError:
                data["departure_date"] = None

        return data

    except json.JSONDecodeError as e:
        log.debug("JSON parse error: %s | text: %.80s", e, text)
        return None
    except Exception as e:
        log.debug("Parse error: %s", e)
        return None


def _plan_text(plan: dict | None) -> str:
    if not plan:
        return "(no current plan)"
    intent = plan.get("intent", {})
    dates  = intent.get("dates", {})
    return (
        f"Destination: {intent.get('destination')} ({intent.get('city_code')})\n"
        f"Dates: {dates.get('departure_date')} → {dates.get('return_date')} ({dates.get('nights')} nights)\n"
        f"Guests: {intent.get('guests')} ({intent.get('adults')} adults, {intent.get('children','0')} children)\n"
        f"Budget: £{intent.get('budget_gbp')} | Hotel: {intent.get('preferences',{}).get('min_hotel_stars','?')}★\n"
        f"Total: £{plan.get('total_cost_gbp','?')}"
    )


def _hist_text(history: list) -> str:
    if not history:
        return "(no prior conversation)"
    return "\n".join(
        f"[{t.get('role','user').upper()}]: {str(t.get('content',''))[:250]}"
        for t in history
    )
